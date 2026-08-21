from __future__ import annotations

import pytest

from liviana.errors import BadRequest, BudgetExhausted, RateLimited

SESSION = "session-0001"


def test_first_message_has_no_history(service, model):
    result = service.reply(SESSION, "Was ist Bambera?")

    assert result.answer == "ok"
    assert result.turns_in_context == 0
    assert model.calls[0]["messages"] == [
        {"role": "user", "content": "Was ist Bambera?"}
    ]


def test_history_is_replayed_as_alternating_turns(service, model):
    service.reply(SESSION, "erste Frage")
    service.reply(SESSION, "zweite Frage")

    assert [m["role"] for m in model.calls[-1]["messages"]] == [
        "user",
        "assistant",
        "user",
    ]
    assert model.calls[-1]["messages"][0]["content"] == "erste Frage"
    assert model.calls[-1]["messages"][1]["content"] == "ok"


def test_window_is_trimmed_fifo_on_write(make_service, model):
    """The stored item never grows beyond the configured window."""
    service = make_service(history_pairs=3)

    for index in range(6):
        service.reply(SESSION, f"Frage {index}")

    stored = service.conversations.recent_turns(SESSION, 99)
    assert [t.user for t in stored] == ["Frage 3", "Frage 4", "Frage 5"]

    sent = model.calls[-1]["messages"]
    assert len(sent) == 3 * 2 + 1  # three pairs plus the new message
    assert sent[0]["content"] == "Frage 2"
    assert sent[-1]["content"] == "Frage 5"


def test_sessions_do_not_see_each_other(service, model):
    service.reply("session-aaaa", "Frage A")
    service.reply("session-bbbb", "Frage B")

    assert len(model.calls[-1]["messages"]) == 1


def test_missing_session_id_gets_one_generated(service):
    result = service.reply(None, "hallo")
    assert len(result.session_id) == 32


def test_a_generated_session_id_carries_the_conversation(service, model):
    first = service.reply(None, "erste Frage")
    service.reply(first.session_id, "zweite Frage")

    assert len(model.calls[-1]["messages"]) == 3


@pytest.mark.parametrize("bad", ["short", "has spaces", "a" * 65, "with#hash"])
def test_malformed_session_id_is_rejected(service, bad):
    with pytest.raises(BadRequest):
        service.reply(bad, "hallo")


@pytest.mark.parametrize("bad", [None, "", "   ", 42])
def test_empty_message_is_rejected(service, bad):
    with pytest.raises(BadRequest):
        service.reply(SESSION, bad)


def test_overlong_message_is_truncated_not_refused(make_service, model):
    """The document says to trim an absurdly long message, not to reject it."""
    service = make_service(max_message_chars=10)

    result = service.reply(SESSION, "x" * 50)

    assert result.message_truncated is True
    assert model.calls[0]["messages"][0]["content"] == "x" * 10


def test_a_normal_message_is_not_flagged_as_truncated(service):
    assert service.reply(SESSION, "hallo").message_truncated is False


def test_control_characters_are_stripped(service, model):
    service.reply(SESSION, "  hallo\x00\x07 welt  ")
    assert model.calls[0]["messages"][0]["content"] == "hallo welt"


def test_rate_limit_trips_at_the_configured_number(make_service, model):
    service = make_service(rate_limit_per_minute=3)

    for _ in range(3):
        service.reply(SESSION, "hallo")

    with pytest.raises(RateLimited) as excinfo:
        service.reply(SESSION, "hallo")

    assert 0 < excinfo.value.retry_after <= 60
    assert len(model.calls) == 3  # the rejected message never reached the model


def test_rate_limit_is_per_session(make_service):
    service = make_service(rate_limit_per_minute=1)

    service.reply("session-aaaa", "hallo")
    service.reply("session-bbbb", "hallo")  # different session, still allowed

    with pytest.raises(RateLimited):
        service.reply("session-aaaa", "hallo")


def test_sessionless_requests_are_limited_by_ip(make_service):
    """Rotating session ids must not hand out a fresh allowance per message."""
    service = make_service(rate_limit_per_minute=2)

    service.reply(None, "hallo", "203.0.113.9")
    service.reply(None, "hallo", "203.0.113.9")

    with pytest.raises(RateLimited):
        service.reply(None, "hallo", "203.0.113.9")

    service.reply(None, "hallo", "203.0.113.10")  # a different visitor is fine


def test_a_supplied_session_wins_over_the_ip(make_service):
    """Two visitors behind one NAT must not share an allowance."""
    service = make_service(rate_limit_per_minute=1)

    service.reply("session-aaaa", "hallo", "203.0.113.9")
    service.reply("session-bbbb", "hallo", "203.0.113.9")


def test_circuit_breaker_stops_all_sessions(make_service, model):
    service = make_service(daily_invocation_limit=2)

    service.reply("session-aaaa", "hallo")
    service.reply("session-bbbb", "hallo")

    with pytest.raises(BudgetExhausted):
        service.reply("session-cccc", "hallo")
    assert len(model.calls) == 2


def test_rejected_requests_do_not_consume_budget(make_service):
    """A 429 must not spend one of the day's invocations."""
    service = make_service(rate_limit_per_minute=1, daily_invocation_limit=2)

    service.reply("session-aaaa", "hallo")
    with pytest.raises(RateLimited):
        service.reply("session-aaaa", "hallo")

    assert service.limits.stats()["invocations_today"] == 1
    service.reply("session-bbbb", "hallo")  # the second invocation is still available


def test_answer_is_stored_for_the_next_turn(service):
    service.reply(SESSION, "Frage")
    turns = service.conversations.recent_turns(SESSION, 4)

    assert len(turns) == 1
    assert turns[0].user == "Frage"
    assert turns[0].assistant == "ok"


def test_model_receives_the_configured_inference_settings(service, model):
    service.reply(SESSION, "Frage")
    assert model.calls[0]["temperature"] == 0.2
    assert model.calls[0]["max_tokens"] == 400
