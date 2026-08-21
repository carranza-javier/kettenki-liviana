from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from liviana.config import Config  # noqa: E402
from liviana.service import LivianaService  # noqa: E402


@pytest.fixture
def content() -> dict:
    return json.loads((ROOT / "content" / "content.json").read_text(encoding="utf-8"))


@pytest.fixture
def content_source(content):
    class _Source:
        loads = 0

        def load(self):
            _Source.loads += 1
            return content

    return _Source()


@pytest.fixture
def make_config(tmp_path):
    def _make(**overrides) -> Config:
        base = dict(
            backend="mock",
            region="eu-central-1",
            content_bucket="",
            content_key="content.json",
            content_path=str(ROOT / "content" / "content.json"),
            content_cache_ttl_s=300,
            conversations_table="",
            limits_table="",
            state_path=str(tmp_path / "state.json"),
            model_id="mock-model",
            max_tokens=400,
            temperature=0.2,
            history_pairs=4,
            conversation_ttl_hours=24,
            rate_limit_per_minute=20,
            daily_invocation_limit=500,
            max_message_chars=1000,
            allowed_origin="*",
        )
        base.update(overrides)
        return Config(**base)

    return _make


class RecordingModel:
    """Captures what the service actually sends to the model."""

    def __init__(self, answer: str = "ok") -> None:
        self.answer = answer
        self.calls: list[dict] = []

    def complete(self, *, system_prompt, messages, max_tokens, temperature):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        return self.answer


@pytest.fixture
def model() -> RecordingModel:
    return RecordingModel()


@pytest.fixture
def service(make_config, content_source, model):
    from liviana.adapters.local_store import LocalStore

    config = make_config()
    store = LocalStore(config.state_path)
    return LivianaService(
        config=config,
        content_source=content_source,
        conversations=store,
        limits=store,
        model=model,
    )


@pytest.fixture
def make_service(make_config, content_source, model):
    """A service with the same store standing in for both tables."""
    from liviana.adapters.local_store import LocalStore

    def _make(**overrides):
        config = make_config(**overrides)
        store = LocalStore(config.state_path)
        return LivianaService(
            config=config,
            content_source=content_source,
            conversations=store,
            limits=store,
            model=model,
        )

    return _make
