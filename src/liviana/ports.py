"""The seams between the domain logic and the outside world.

The service in ``service.py`` only ever talks to these protocols, which is what
lets the exact same flow run against local JSON files (phase 1) and against
S3 + DynamoDB + Bedrock (phase 2).

The split between ``ConversationStore`` and ``LimitStore`` mirrors the two
DynamoDB tables described in the architecture document: one holds the sliding
window of a conversation, the other holds the two abuse counters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Turn:
    """One completed exchange: what the visitor asked, what Liviana replied."""

    user: str
    assistant: str
    created_at: int  # unix seconds


class ContentSource(Protocol):
    """The client's knowledge document, cached in the execution environment."""

    def load(self) -> dict[str, Any]:
        ...


class ModelClient(Protocol):
    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        ...


class ConversationStore(Protocol):
    """One item per session holding the sliding window, expired by TTL."""

    def recent_turns(self, session_id: str, limit: int) -> list[Turn]:
        """The stored window, oldest first, at most ``limit`` turns."""

    def save_turns(self, session_id: str, turns: list[Turn], ttl_seconds: int) -> None:
        """Replace the stored window with ``turns``, expiring in ``ttl_seconds``.

        The caller has already trimmed the list to the configured window, so
        the item can never grow: what is written is what will be read back.
        """


class LimitStore(Protocol):
    """The two counters that protect the budget.

    Both are enforced with a single conditional update, so two concurrent
    invocations cannot both slip past a limit, and a rejected request neither
    writes nor counts.
    """

    def register_message(self, key: str, limit_per_minute: int) -> bool:
        """Count one message against ``key``'s per-minute allowance.

        Returns False when the key is already at the limit, in which case
        nothing was counted.
        """

    def register_invocation(self, daily_limit: int) -> bool:
        """Count one model invocation against today's global allowance.

        Returns False when the circuit breaker is open, in which case nothing
        was counted and no model call must be made.
        """

    def seconds_until_next_minute(self) -> int:
        """How long the caller should wait before retrying after a 429."""
