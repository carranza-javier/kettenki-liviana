#!/usr/bin/env python
"""Verifies a deployed Liviana API against the contract in API.md.

    python tools/smoke.py https://abc123.execute-api.eu-central-1.amazonaws.com

Every check costs at most one Bedrock invocation, and --flood costs one per
message, so mind the daily budget when running it against production.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid

TIMEOUT = 30


def call(base: str, path: str, payload: dict | None = None, method: str = "POST"):
    url = base.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body}


class Checks:
    def __init__(self) -> None:
        self.failures = 0

    def expect(self, label: str, condition: bool, detail: str = "") -> None:
        mark = "ok  " if condition else "FAIL"
        print(f"  [{mark}] {label}{'  ' + detail if detail and not condition else ''}")
        if not condition:
            self.failures += 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="stack output ChatEndpoint, without /chat")
    parser.add_argument("--flood", type=int, default=0, help="messages to send to trip the rate limit")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    if base.endswith("/chat"):
        base = base[: -len("/chat")]

    checks = Checks()
    session = uuid.uuid4().hex

    print("health")
    status, body = call(base, "/health", method="GET")
    checks.expect("GET /health is 200", status == 200, str(status))
    checks.expect("reports the aws backend", body.get("backend") == "aws", str(body))

    print("first message")
    status, body = call(base, "/chat", {"message": "Was ist Bambera?", "sessionId": session})
    checks.expect("POST /chat is 200", status == 200, str(body))
    checks.expect("answer is present", bool(body.get("answer")), str(body))
    checks.expect("session echoed back", body.get("sessionId") == session, str(body))
    checks.expect("no history yet", body.get("meta", {}).get("turnsInContext") == 0, str(body))
    if body.get("answer"):
        print(f"       -> {body['answer'][:160]}")

    print("follow-up in the same session")
    status, body = call(base, "/chat", {"message": "Und wer nutzt das?", "sessionId": session})
    checks.expect("POST /chat is 200", status == 200, str(body))
    checks.expect(
        "previous turn was replayed",
        body.get("meta", {}).get("turnsInContext", 0) >= 1,
        str(body),
    )
    if body.get("answer"):
        print(f"       -> {body['answer'][:160]}")

    print("session id is issued when omitted")
    status, body = call(base, "/chat", {"message": "Hallo"})
    checks.expect("POST /chat is 200", status == 200, str(body))
    checks.expect("sessionId returned", bool(body.get("sessionId")), str(body))

    print("validation")
    status, body = call(base, "/chat", {"message": "   ", "sessionId": session})
    checks.expect("empty message is 400", status == 400, f"{status} {body}")
    checks.expect("error code is bad_request", body.get("error") == "bad_request", str(body))

    status, body = call(base, "/chat", {"message": "hi", "sessionId": "no"})
    checks.expect("bad sessionId is 400", status == 400, f"{status} {body}")

    status, body = call(base, "/chat", {"message": "x" * 5000, "sessionId": session})
    checks.expect("overlong message is truncated, not refused", status == 200, f"{status} {body}")
    checks.expect(
        "truncation is reported",
        body.get("meta", {}).get("messageTruncated") is True,
        str(body),
    )

    if args.flood:
        print(f"rate limit ({args.flood} messages)")
        flood_session = uuid.uuid4().hex
        limited = False
        for index in range(args.flood):
            status, body = call(base, "/chat", {"message": "Hallo", "sessionId": flood_session})
            if status == 429:
                limited = True
                checks.expect("error code is rate_limited", body.get("error") == "rate_limited", str(body))
                checks.expect("retryAfter is present", isinstance(body.get("retryAfter"), int), str(body))
                print(f"       tripped after {index} accepted messages")
                break
        checks.expect("rate limit tripped", limited, "increase --flood")

    print()
    if checks.failures:
        print(f"{checks.failures} check(s) failed.")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
