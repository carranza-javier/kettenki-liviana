"""The conversation flow, identical in both backends.

Order of operations, and why:

  1. validate           cheapest rejection first, costs nothing
  2. rate limit         rejects abuse before any read
  3. read history       one read: the session's stored window
  4. build prompt       system prompt + trimmed history + the new message
  5. circuit breaker    counted immediately before the paid call, so a
                        rejected request never consumes budget
  6. model call         the only paid step
  7. write history      one write of the trimmed window, with TTL

Steps 2 and 5 are two different protections: 2 stops one visitor hammering the
widget, 5 caps what the whole site can cost in a day no matter how many
visitors there are.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass

from .config import Config
from .errors import BadRequest, BudgetExhausted, RateLimited
from .ports import ContentSource, ConversationStore, LimitStore, ModelClient, Turn
from .prompt import build_system_prompt

logger = logging.getLogger(__name__)

# Opaque, client-generated identifier. Kept deliberately narrow: it becomes a
# DynamoDB partition key, so no separators and no unbounded length.
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@dataclass(frozen=True)
class Reply:
    answer: str
    session_id: str
    turns_in_context: int
    elapsed_ms: int
    message_truncated: bool = False


def new_session_id() -> str:
    return uuid.uuid4().hex


def _clean(text: str) -> str:
    """Drop control characters, keep everything a human would actually type."""
    return "".join(
        ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C"
    ).strip()


class LivianaService:
    def __init__(
        self,
        config: Config,
        content_source: ContentSource,
        conversations: ConversationStore,
        limits: LimitStore,
        model: ModelClient,
    ) -> None:
        self._config = config
        self._content = content_source
        self._conversations = conversations
        self._limits = limits
        self._model = model

    # Exposed for the terminal client's inspection commands and for tests;
    # the request flow itself never reaches around the service.
    @property
    def config(self) -> Config:
        return self._config

    @property
    def conversations(self) -> ConversationStore:
        return self._conversations

    @property
    def limits(self) -> LimitStore:
        return self._limits

    @property
    def content_source(self) -> ContentSource:
        return self._content

    def reply(
        self,
        session_id: str | None,
        message: str | None,
        client_ip: str | None = None,
    ) -> Reply:
        started = time.monotonic()
        config = self._config

        supplied_session = self._validated_session_id(session_id)
        session_id = supplied_session or new_session_id()
        message, truncated = self._validated_message(message)

        # The architecture document says: count per session, or per IP when
        # there is no session yet. A first message arrives without one, so
        # rotating session ids to escape the limit only works while the caller
        # keeps arriving from new addresses -- and the API Gateway throttle and
        # the daily circuit breaker cover that case.
        limit_key = supplied_session or client_ip or session_id
        if not self._limits.register_message(limit_key, config.rate_limit_per_minute):
            raise RateLimited(
                f"Too many messages from this session "
                f"({config.rate_limit_per_minute} per minute).",
                retry_after=self._limits.seconds_until_next_minute(),
            )

        history = self._conversations.recent_turns(session_id, config.history_pairs)
        content = self._content.load()
        system_prompt = build_system_prompt(content)
        messages = self._as_messages(history, message)

        if not self._limits.register_invocation(config.daily_invocation_limit):
            logger.warning(
                "Circuit breaker open: daily limit of %s invocations reached.",
                config.daily_invocation_limit,
            )
            raise BudgetExhausted(
                "The daily invocation budget for this assistant is used up."
            )

        answer = self._model.complete(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )

        # FIFO: append the new pair, drop the oldest beyond the window.
        turn = Turn(user=message, assistant=answer, created_at=int(time.time()))
        window = (history + [turn])[-config.history_pairs :] if config.history_pairs else []
        self._conversations.save_turns(session_id, window, config.conversation_ttl_seconds)

        return Reply(
            answer=answer,
            session_id=session_id,
            turns_in_context=len(history),
            elapsed_ms=int((time.monotonic() - started) * 1000),
            message_truncated=truncated,
        )

    # -- helpers -----------------------------------------------------------
    def _validated_session_id(self, session_id: str | None) -> str | None:
        """Returns the client's id, or None when it did not supply one."""
        if session_id is None or session_id == "":
            # First message of a conversation: the widget may leave it out and
            # keep whatever comes back in the response.
            return None
        if not isinstance(session_id, str) or not _SESSION_ID_PATTERN.match(session_id):
            raise BadRequest(
                "sessionId must be 8 to 64 characters of A-Z, a-z, 0-9, '-' or '_'."
            )
        return session_id

    def _validated_message(self, message: str | None) -> tuple[str, bool]:
        if not isinstance(message, str):
            raise BadRequest("message is required and must be a string.")
        cleaned = _clean(message)
        if not cleaned:
            raise BadRequest("message must not be empty.")
        limit = self._config.max_message_chars
        if len(cleaned) > limit:
            # Truncate rather than refuse: an absurdly long paste is a cost
            # problem, not a reason to make the visitor retype their question.
            # The response says it happened so the widget can mention it.
            logger.info("Message truncated from %s to %s characters.", len(cleaned), limit)
            return cleaned[:limit], True
        return cleaned, False

    @staticmethod
    def _as_messages(history: list[Turn], message: str) -> list[dict[str, str]]:
        """Flatten stored turns into the alternating array the model expects."""
        messages: list[dict[str, str]] = []
        for turn in history:
            messages.append({"role": "user", "content": turn.user})
            messages.append({"role": "assistant", "content": turn.assistant})
        messages.append({"role": "user", "content": message})
        return messages
