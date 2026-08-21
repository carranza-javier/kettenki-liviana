#!/usr/bin/env python
"""Terminal client for Liviana.

Runs the exact same service the Lambda runs, so what you see here is what the
widget will get. Defaults to the mock backend, which needs no AWS account.

    python tools/chat.py                      interactive, mock backend
    python tools/chat.py -m "Was ist Bambera?"  one question and exit
    python tools/chat.py --backend aws        against real AWS resources

Commands inside the session:

    /new      start a fresh session id (drops the conversation memory)
    /session  show the current session id
    /history  show what is currently stored for this session
    /state    show session count and today's invocation count
    /prompt   print the system prompt that is being sent
    /flood N  send N messages in a row, to watch the rate limiter trip
    /quit     leave
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from liviana.config import ConfigError, load_config  # noqa: E402
from liviana.errors import LivianaError  # noqa: E402
from liviana.factory import build_service  # noqa: E402
from liviana.prompt import build_system_prompt  # noqa: E402
from liviana.service import new_session_id  # noqa: E402

DIM = "\033[2m"
BOLD = "\033[1m"
RED = "\033[31m"
RESET = "\033[0m"


def _supports_colour() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _style(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if _supports_colour() else text


def _ask(service, session_id: str, message: str) -> str:
    try:
        result = service.reply(session_id, message)
    except LivianaError as exc:
        detail = f" (retry in {exc.retry_after}s)" if exc.retry_after else ""
        print(_style(f"  [{exc.status_code} {exc.code}] {exc.message}{detail}", RED))
        return session_id

    print(f"  {result.answer}")
    print(
        _style(
            f"  ({result.turns_in_context} turns in context, {result.elapsed_ms} ms)",
            DIM,
        )
    )
    return result.session_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Talk to Liviana from the terminal.")
    parser.add_argument("--backend", choices=["mock", "aws"], help="overrides LIVIANA_BACKEND")
    parser.add_argument("-m", "--message", help="ask one question and exit")
    parser.add_argument("-s", "--session", help="reuse an existing session id")
    args = parser.parse_args()

    if args.backend:
        os.environ["LIVIANA_BACKEND"] = args.backend
    os.environ.setdefault("LIVIANA_BACKEND", "mock")

    try:
        config = load_config()
        service = build_service(config)
    except ConfigError as exc:
        print(_style(f"Configuration error: {exc}", RED), file=sys.stderr)
        return 2

    session_id = args.session or new_session_id()

    if args.message:
        _ask(service, session_id, args.message)
        return 0

    print(_style(f"Liviana [{config.backend}]", BOLD))
    print(
        _style(
            f"  model={config.model_id} temp={config.temperature} "
            f"history={config.history_pairs} pairs  "
            f"limits={config.rate_limit_per_minute}/min, "
            f"{config.daily_invocation_limit}/day",
            DIM,
        )
    )
    print(_style(f"  session {session_id}  (/quit to leave)\n", DIM))

    while True:
        try:
            message = input(_style("you> ", BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not message:
            continue

        command, _, argument = message.partition(" ")
        command = command.lower()

        if command in ("/quit", "/exit"):
            return 0
        if command == "/new":
            session_id = new_session_id()
            print(_style(f"  new session {session_id}", DIM))
            continue
        if command == "/session":
            print(_style(f"  {session_id}", DIM))
            continue
        if command == "/history":
            turns = service.conversations.recent_turns(session_id, config.history_pairs)
            if not turns:
                print(_style("  (empty)", DIM))
            for turn in turns:
                print(_style(f"  you> {turn.user}", DIM))
                print(_style(f"  liv> {turn.assistant}", DIM))
            continue
        if command == "/state":
            store = service.limits
            stats = store.stats() if hasattr(store, "stats") else {}
            print(_style(f"  {stats or 'not available for this backend'}", DIM))
            continue
        if command == "/prompt":
            print(build_system_prompt(service.content_source.load()))
            continue
        if command == "/flood":
            count = int(argument) if argument.strip().isdigit() else 25
            for index in range(count):
                print(_style(f"  #{index + 1}", DIM), end=" ")
                session_id = _ask(service, session_id, "Was ist KettenKI?")
            continue

        session_id = _ask(service, session_id, message)


if __name__ == "__main__":
    raise SystemExit(main())
