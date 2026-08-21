"""Handler-level tests: the contract in API.md, verified."""

from __future__ import annotations

import json

import pytest

from liviana import app, factory


@pytest.fixture(autouse=True)
def wired(monkeypatch, make_service):
    service = make_service(
        rate_limit_per_minute=2,
        daily_invocation_limit=3,
        allowed_origin="https://example.test",
    )
    config = service.config
    monkeypatch.setattr(factory, "_cached", (config, service))
    monkeypatch.setattr(app, "get_service", lambda: (config, service))
    return service


def _event(
    body: dict | str | None,
    method: str = "POST",
    path: str = "/chat",
    source_ip: str = "203.0.113.1",
) -> dict:
    return {
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": source_ip},
            "requestId": "req-1",
        },
        "rawPath": path,
        "body": body if isinstance(body, (str, type(None))) else json.dumps(body),
    }


def _body(response: dict) -> dict:
    return json.loads(response["body"])


def test_happy_path_returns_answer_and_session(wired):
    response = app.handler(_event({"message": "Was ist Bambera?", "sessionId": "session-0001"}))

    assert response["statusCode"] == 200
    body = _body(response)
    assert body["answer"] == "ok"
    assert body["sessionId"] == "session-0001"
    assert body["meta"]["turnsInContext"] == 0
    assert "elapsedMs" in body["meta"]


def test_session_id_is_issued_when_absent():
    response = app.handler(_event({"message": "hallo"}))
    assert response["statusCode"] == 200
    assert len(_body(response)["sessionId"]) == 32


def test_cors_headers_use_the_configured_origin():
    response = app.handler(_event({"message": "hallo"}))
    assert response["headers"]["Access-Control-Allow-Origin"] == "https://example.test"


def test_preflight_is_answered_without_touching_the_model(model):
    response = app.handler(_event(None, method="OPTIONS"))
    assert response["statusCode"] == 204
    assert model.calls == []


def test_health_check_does_not_touch_the_model(model):
    response = app.handler(_event(None, method="GET", path="/health"))
    assert response["statusCode"] == 200
    assert _body(response)["status"] == "ok"
    assert model.calls == []


def test_other_methods_are_rejected():
    assert app.handler(_event(None, method="DELETE"))["statusCode"] == 405


def test_an_overlong_message_is_truncated_and_flagged():
    response = app.handler(_event({"message": "x" * 5000, "sessionId": "session-0001"}))

    assert response["statusCode"] == 200
    assert _body(response)["meta"]["messageTruncated"] is True


@pytest.mark.parametrize("body", ["not json", json.dumps([1, 2]), json.dumps({})])
def test_malformed_requests_are_400(body):
    response = app.handler(_event(body))
    assert response["statusCode"] == 400
    assert _body(response)["error"] == "bad_request"


def test_rate_limit_returns_429_with_retry_after():
    for _ in range(2):
        app.handler(_event({"message": "hallo", "sessionId": "session-0001"}))

    response = app.handler(_event({"message": "hallo", "sessionId": "session-0001"}))

    assert response["statusCode"] == 429
    assert _body(response)["error"] == "rate_limited"
    assert _body(response)["retryAfter"] > 0
    assert response["headers"]["Retry-After"]


def test_circuit_breaker_returns_503():
    for index in range(3):
        app.handler(_event({"message": "hallo", "sessionId": f"session-000{index}"}))

    response = app.handler(_event({"message": "hallo", "sessionId": "session-9999"}))

    assert response["statusCode"] == 503
    assert _body(response)["error"] == "budget_exhausted"


def test_unexpected_failures_do_not_leak_details(monkeypatch, wired):
    def explode(*args, **kwargs):
        raise RuntimeError("bucket kettenki-secret-name does not exist")

    monkeypatch.setattr(wired, "reply", explode)
    response = app.handler(_event({"message": "hallo"}))

    assert response["statusCode"] == 500
    assert "kettenki-secret-name" not in response["body"]


def test_direct_invoke_payload_is_accepted():
    """Console tests and the smoke script pass the fields flat."""
    response = app.handler({"message": "hallo", "sessionId": "session-0001"})
    assert response["statusCode"] == 200
