"""Mock model: deterministic answers built from the content document.

It exists so the whole flow -- history read, prompt build, answer, history write,
rate limit, circuit breaker -- can be exercised from the terminal without an
AWS account and without spending a single Bedrock invocation. It deliberately
reads its answers out of the same content document the real prompt is built
from, so a wrong or missing piece of content shows up in the mock too.

It is not a language model and does not pretend to be one: it matches keywords.
"""

from __future__ import annotations

import re
from typing import Any

_LANG_SIGNALS = {
    "de": ["was", "wie", "wer", "warum", "welche", "kannst", "der", "die", "das", "ich", "ist"],
    "en": ["what", "how", "who", "why", "which", "can", "the", "is", "are", "you"],
    "es": ["qué", "que", "cómo", "como", "quién", "por qué", "cuál", "el", "la", "es"],
    "fr": ["quoi", "comment", "qui", "pourquoi", "quel", "quelle", "le", "la", "est"],
}

_PRICE_WORDS = ["preis", "preise", "kost", "price", "cost", "precio", "cuánto", "cuanto",
                "prix", "coût", "tarif", "offerte", "angebot", "quote"]
_CONTACT_WORDS = ["kontakt", "contact", "contacto", "email", "e-mail", "mail", "linkedin",
                  "erreichen", "reach", "escribir", "demo", "test", "probieren", "probar"]
_OUT_OF_SCOPE_WORDS = ["lebenslauf", "cv", "resume", "job", "stelle", "bewerb", "gehalt",
                       "salary", "salario", "empleo", "trabajo", "interview", "anstellung",
                       "hire", "contratar", "system prompt", "systemprompt"]
_FOLLOW_UP_WORDS = ["das", "es", "sie", "it", "that", "this", "eso", "ello", "ça", "cela",
                    "und", "and", "y", "et", "mehr", "more", "más", "mas", "plus"]


def _detect_language(text: str, default: str) -> str:
    words = re.findall(r"[\wÀ-ÿ]+", text.lower())
    if not words:
        return default
    scores = {
        lang: sum(1 for signal in signals if signal in words)
        for lang, signals in _LANG_SIGNALS.items()
    }
    best = max(scores.items(), key=lambda item: item[1])
    return best[0] if best[1] > 0 else default


def _localised(mapping: Any, language: str, default_language: str) -> str:
    if isinstance(mapping, dict):
        return mapping.get(language) or mapping.get(default_language) or next(
            iter(mapping.values()), ""
        )
    return str(mapping or "")


def _find_products(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    for section in content.get("sections", []):
        data = section.get("data", {})
        products = {
            key: value
            for key, value in data.items()
            if isinstance(value, dict) and "beschreibung" in value
        }
        if products:
            return products
    return {}


class MockModelClient:
    """Answers from the content document, no network involved."""

    def __init__(self, content_source: Any) -> None:
        self._content_source = content_source

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        content = self._content_source.load()
        default_language = content.get("language", {}).get("default", "de")

        question = messages[-1]["content"] if messages else ""
        history = [m for m in messages[:-1] if m["role"] == "user"]
        language = _detect_language(question, default_language)
        lowered = question.lower()

        if any(word in lowered for word in _OUT_OF_SCOPE_WORDS):
            return _localised(
                content.get("out_of_scope", {}).get("response"), language, default_language
            )

        if any(word in lowered for word in _PRICE_WORDS):
            statement = _localised(
                content.get("pricing", {}).get("statement"), language, default_language
            )
            cta = _localised(content.get("cta", {}).get("text"), language, default_language)
            return f"{statement} {cta}".strip()

        if any(word in lowered for word in _CONTACT_WORDS):
            return _localised(content.get("cta", {}).get("text"), language, default_language)

        products = _find_products(content)
        for key, product in products.items():
            if key in lowered or product.get("name", "").lower() in lowered:
                return f"{product.get('claim', '')}. {product.get('beschreibung', '')}".strip()

        # Nothing matched. If this is a short follow-up and there is history,
        # answer against the previous question -- that is what proves the
        # conversation memory is actually being passed through.
        if history and (len(lowered.split()) <= 6 or any(w in lowered.split() for w in _FOLLOW_UP_WORDS)):
            previous = history[-1]["content"]
            for key, product in products.items():
                if key in previous.lower() or product.get("name", "").lower() in previous.lower():
                    extras = product.get("vorteile") or []
                    joined = "; ".join(extras[:3])
                    return (
                        f"Zu {product.get('name', key)}: {joined}."
                        if joined
                        else product.get("beschreibung", "")
                    )

        # Last resort: the first prose field of the first section, which by
        # convention is the "what is this company" paragraph.
        for section in content.get("sections", []):
            for value in section.get("data", {}).values():
                if isinstance(value, str) and len(value) > 40:
                    return value

        return _localised(
            content.get("out_of_scope", {}).get("response"), language, default_language
        )
