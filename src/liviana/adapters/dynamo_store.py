"""Production stores: two DynamoDB tables, both on-demand, both with TTL.

Conversations table -- partition key ``sessionId``, one item per session:

    { sessionId, turns: [ {user, assistant, created_at}, ... ], expires_at }

One item holding the sliding window, as the architecture document specifies.
The service trims the list to the configured number of pairs before handing it
over, so the item is bounded by construction and a whole conversation is one
read and one write. The write replaces the window rather than appending to it,
because DynamoDB cannot drop the oldest element of a list server-side.

That makes the write a read-modify-write: two messages of the *same* session
arriving at the same instant could lose one turn. Visitors type serially and
the rate limiter bounds the rest, so this is accepted rather than defended
against with a version attribute.

Limits table -- partition key ``id``, one item per counter window:

    RATE#<session-or-ip>#<epoch_minute>   hits, expires_at (2 min)
    BUDGET#<YYYY-MM-DD>                   hits, expires_at (48 h)

Both counters are enforced with a single conditional UpdateItem, so two
concurrent invocations cannot both slip past a limit. When the condition fails,
nothing was written and nothing was counted -- a rejected request never
consumes budget.

The windows are fixed, not sliding: the minute bucket comes from the clock, so
a visitor can in the worst case send 2x the limit across a window boundary.
That is the standard trade-off and it is deliberate -- a sliding window costs an
extra read per message to defend against an edge case that a public marketing
chatbot does not care about.
"""

from __future__ import annotations

import time

from ..ports import Turn


def _now() -> int:
    return int(time.time())


def _table(name: str, region: str):
    import boto3

    return boto3.resource("dynamodb", region_name=region).Table(name)


class DynamoConversationStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _table(table_name, region)

    def recent_turns(self, session_id: str, limit: int) -> list[Turn]:
        response = self._table.get_item(
            Key={"sessionId": session_id}, ConsistentRead=False
        )
        item = response.get("Item")
        if not item:
            return []
        # A TTL deletion can lag by up to 48 hours, so an expired item may
        # still be readable. Treat it as gone.
        if int(item.get("expires_at", 0)) <= _now():
            return []
        return [
            Turn(
                user=turn["user"],
                assistant=turn["assistant"],
                created_at=int(turn["created_at"]),
            )
            for turn in item.get("turns", [])[-limit:]
        ]

    def save_turns(self, session_id: str, turns: list[Turn], ttl_seconds: int) -> None:
        self._table.put_item(
            Item={
                "sessionId": session_id,
                "turns": [
                    {
                        "user": turn.user,
                        "assistant": turn.assistant,
                        "created_at": turn.created_at,
                    }
                    for turn in turns
                ],
                "expires_at": _now() + ttl_seconds,
            }
        )


class DynamoLimitStore:
    def __init__(self, table_name: str, region: str) -> None:
        from botocore.exceptions import ClientError

        self._client_error = ClientError
        self._table = _table(table_name, region)

    def _try_increment(self, key: str, limit: int, ttl_seconds: int) -> bool:
        try:
            self._table.update_item(
                Key={"id": key},
                UpdateExpression=(
                    "SET expires_at = if_not_exists(expires_at, :ttl) ADD hits :one"
                ),
                ConditionExpression="attribute_not_exists(hits) OR hits < :limit",
                ExpressionAttributeValues={
                    ":one": 1,
                    ":limit": limit,
                    ":ttl": _now() + ttl_seconds,
                },
            )
            return True
        except self._client_error as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def register_message(self, key: str, limit_per_minute: int) -> bool:
        now = _now()
        return self._try_increment(
            f"RATE#{key}#{now // 60}", limit_per_minute, ttl_seconds=120
        )

    def register_invocation(self, daily_limit: int) -> bool:
        now = _now()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        return self._try_increment(f"BUDGET#{day}", daily_limit, ttl_seconds=172800)

    def seconds_until_next_minute(self) -> int:
        return 60 - (_now() % 60)
