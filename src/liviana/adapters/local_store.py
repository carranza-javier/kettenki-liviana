"""Mock store: both DynamoDB tables in one local JSON file.

This is a faithful stand-in, not a shortcut. Same item shapes, same fixed
one-minute rate-limit window, same daily budget window, same expiry semantics,
so the behaviour observed from the terminal in phase 1 is the behaviour the
widget will see in production. The only thing it cannot reproduce is DynamoDB's
atomicity, which does not matter in a single-process test.

Expired rows are dropped on read, which is what DynamoDB's TTL does (lazily,
within about 48 hours). Nothing here relies on a row disappearing the instant
it expires: every counter key already contains its own time window, and every
conversation item carries its own expiry.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..ports import Turn

_EMPTY: dict[str, Any] = {"conversations": {}, "limits": {}}


def _now() -> int:
    return int(time.time())


def _minute_bucket(now: int) -> int:
    return now // 60


def _day_bucket(now: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


class LocalStore:
    """Implements ConversationStore and LimitStore against one file."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    # -- persistence -------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return json.loads(json.dumps(_EMPTY))
        try:
            state = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return json.loads(json.dumps(_EMPTY))
        for bucket in _EMPTY:
            state.setdefault(bucket, {})
        return self._expire(state)

    def _write(self, state: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace so an interrupted run cannot leave a truncated file.
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @staticmethod
    def _expire(state: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        for bucket in ("conversations", "limits"):
            for key, row in list(state[bucket].items()):
                if row.get("expires_at", 0) <= now:
                    del state[bucket][key]
        return state

    # -- ConversationStore -------------------------------------------------
    def recent_turns(self, session_id: str, limit: int) -> list[Turn]:
        item = self._read()["conversations"].get(session_id)
        if not item:
            return []
        return [
            Turn(user=t["user"], assistant=t["assistant"], created_at=t["created_at"])
            for t in item.get("turns", [])[-limit:]
        ]

    def save_turns(self, session_id: str, turns: list[Turn], ttl_seconds: int) -> None:
        state = self._read()
        state["conversations"][session_id] = {
            "turns": [
                {"user": t.user, "assistant": t.assistant, "created_at": t.created_at}
                for t in turns
            ],
            "expires_at": _now() + ttl_seconds,
        }
        self._write(state)

    # -- LimitStore --------------------------------------------------------
    def _try_increment(self, key: str, limit: int, ttl_seconds: int) -> bool:
        state = self._read()
        row = state["limits"].get(key, {"hits": 0})
        if row["hits"] >= limit:
            return False
        row["hits"] += 1
        row["expires_at"] = _now() + ttl_seconds
        state["limits"][key] = row
        self._write(state)
        return True

    def register_message(self, key: str, limit_per_minute: int) -> bool:
        # Two windows of slack on the TTL, same as the table: cheap, and it
        # keeps the row inspectable while debugging.
        return self._try_increment(
            f"RATE#{key}#{_minute_bucket(_now())}", limit_per_minute, 120
        )

    def register_invocation(self, daily_limit: int) -> bool:
        return self._try_increment(f"BUDGET#{_day_bucket(_now())}", daily_limit, 172800)

    def seconds_until_next_minute(self) -> int:
        return 60 - (_now() % 60)

    # -- test and CLI helpers ---------------------------------------------
    def stats(self) -> dict[str, Any]:
        state = self._read()
        key = f"BUDGET#{_day_bucket(_now())}"
        return {
            "sessions": len(state["conversations"]),
            "invocations_today": state["limits"].get(key, {}).get("hits", 0),
        }
