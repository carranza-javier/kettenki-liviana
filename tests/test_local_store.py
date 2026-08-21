"""The mock store must behave like the two DynamoDB tables, expiry included."""

from __future__ import annotations

import time

import pytest

from liviana.adapters import local_store
from liviana.adapters.local_store import LocalStore
from liviana.ports import Turn


@pytest.fixture
def store(tmp_path):
    return LocalStore(str(tmp_path / "state.json"))


def _turns(*texts: str) -> list[Turn]:
    now = int(time.time())
    return [Turn(user=t, assistant=f"re: {t}", created_at=now) for t in texts]


def test_the_window_round_trips(store):
    store.save_turns("s1", _turns("q0", "q1", "q2"), 3600)

    assert [t.user for t in store.recent_turns("s1", 99)] == ["q0", "q1", "q2"]
    assert [t.user for t in store.recent_turns("s1", 2)] == ["q1", "q2"]


def test_saving_replaces_the_window_rather_than_appending(store):
    store.save_turns("s1", _turns("q0", "q1"), 3600)
    store.save_turns("s1", _turns("q1", "q2"), 3600)

    assert [t.user for t in store.recent_turns("s1", 99)] == ["q1", "q2"]


def test_an_expired_conversation_disappears(store, monkeypatch):
    store.save_turns("s1", _turns("alt"), ttl_seconds=10)
    assert store.recent_turns("s1", 4)

    monkeypatch.setattr(local_store, "_now", lambda: int(time.time()) + 11)
    assert store.recent_turns("s1", 4) == []


def test_an_unknown_session_is_empty(store):
    assert store.recent_turns("nobody", 4) == []


def test_rate_limit_window_rolls_over(store, monkeypatch):
    now = int(time.time())
    monkeypatch.setattr(local_store, "_now", lambda: now)

    assert store.register_message("s1", 2) is True
    assert store.register_message("s1", 2) is True
    assert store.register_message("s1", 2) is False

    monkeypatch.setattr(local_store, "_now", lambda: now + 60)
    assert store.register_message("s1", 2) is True


def test_rate_limit_keys_are_independent(store):
    assert store.register_message("s1", 1) is True
    assert store.register_message("203.0.113.9", 1) is True
    assert store.register_message("s1", 1) is False


def test_daily_budget_rolls_over(store, monkeypatch):
    now = int(time.time())
    monkeypatch.setattr(local_store, "_now", lambda: now)

    assert store.register_invocation(1) is True
    assert store.register_invocation(1) is False

    monkeypatch.setattr(local_store, "_now", lambda: now + 86400)
    assert store.register_invocation(1) is True


def test_a_rejected_increment_stores_nothing(store):
    store.register_invocation(1)
    before = store.stats()["invocations_today"]
    store.register_invocation(1)
    assert store.stats()["invocations_today"] == before


def test_a_corrupt_state_file_does_not_crash(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ not json", encoding="utf-8")

    store = LocalStore(str(path))
    assert store.recent_turns("s1", 4) == []
    assert store.register_message("s1", 5) is True
