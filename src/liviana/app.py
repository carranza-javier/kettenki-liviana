"""Lambda entry point behind an API Gateway HTTP API (payload format 2.0).

The handler does transport only: parse, delegate, map errors to status codes.
All behaviour lives in ``service.py`` so that the terminal client exercises the
identical code path.

The full request/response contract is written down in API.md; the mapping from
exception to status code is in ``errors.py``.
"""

from __future__ import annotations

import base64
import json
import logging
import os

from .errors import BadRequest, LivianaError
from .factory import get_service

logging.basicConfig(level=os.environ.get("LIVIANA_LOG_LEVEL", "INFO"))
logger = logging.getLogger("liviana")

# Visitor messages and answers are personal-ish free text. Logging them is a
# per-deployment decision, so it is off unless switched on.
_LOG_MESSAGES = os.environ.get("LIVIANA_LOG_MESSAGES", "").lower() in ("1", "true")


def _cors_headers(allowed_origin: str) -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": allowed_origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "86400",
    }


def _response(status: int, body: dict, allowed_origin: str, extra: dict | None = None):
    headers = {"Content-Type": "application/json", **_cors_headers(allowed_origin)}
    if extra:
        headers.update(extra)
    return {
        "statusCode": status,
        "headers": headers,
        "body": json.dumps(body, ensure_ascii=False),
    }


def _parse_body(event: dict) -> dict:
    # Direct invoke (console test, integration script) passes the fields flat.
    if "message" in event or "sessionId" in event:
        return event

    raw = event.get("body")
    if raw is None:
        return {}
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise BadRequest("Request body must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise BadRequest("Request body must be a JSON object.")
    return parsed


def _route(event: dict) -> tuple[str, str]:
    context = event.get("requestContext", {}).get("http", {})
    method = context.get("httpMethod") or context.get("method") or "POST"
    path = context.get("path") or event.get("rawPath") or "/chat"
    return method.upper(), path


def _client_ip(event: dict) -> str | None:
    """Fallback rate-limit key for a request that carries no session yet."""
    return event.get("requestContext", {}).get("http", {}).get("sourceIp")


def handler(event, context=None):  # noqa: ANN001 - Lambda signature
    request_id = getattr(context, "aws_request_id", None) or event.get(
        "requestContext", {}
    ).get("requestId", "local")

    try:
        config, service = get_service()
    except Exception:  # configuration errors must not leak details outward
        logger.exception("[%s] configuration failure", request_id)
        return _response(
            500,
            {"error": "internal_error", "message": "The assistant is misconfigured."},
            "*",
        )

    origin = config.allowed_origin
    method, path = _route(event)

    if method == "OPTIONS":
        return _response(204, {}, origin)

    if method == "GET" and path.endswith("/health"):
        return _response(200, {"status": "ok", "backend": config.backend}, origin)

    if method != "POST":
        return _response(
            405, {"error": "method_not_allowed", "message": "Use POST."}, origin
        )

    try:
        body = _parse_body(event)
        result = service.reply(
            body.get("sessionId"), body.get("message"), _client_ip(event)
        )
    except LivianaError as exc:
        payload = {"error": exc.code, "message": exc.message}
        headers = None
        if exc.retry_after is not None:
            payload["retryAfter"] = exc.retry_after
            headers = {"Retry-After": str(exc.retry_after)}
        logger.info("[%s] %s -> %s", request_id, exc.code, exc.status_code)
        return _response(exc.status_code, payload, origin, headers)
    except Exception:
        logger.exception("[%s] unhandled failure", request_id)
        return _response(
            500,
            {"error": "internal_error", "message": "The assistant is unavailable."},
            origin,
        )

    logger.info(
        "[%s] ok session=%s turns=%s %sms%s",
        request_id,
        result.session_id[:8],
        result.turns_in_context,
        result.elapsed_ms,
        f' q="{body.get("message")}" a="{result.answer}"' if _LOG_MESSAGES else "",
    )

    return _response(
        200,
        {
            "answer": result.answer,
            "sessionId": result.session_id,
            "meta": {
                "turnsInContext": result.turns_in_context,
                "elapsedMs": result.elapsed_ms,
                "messageTruncated": result.message_truncated,
            },
        },
        origin,
    )
