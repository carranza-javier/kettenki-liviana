"""Errors that map one to one onto an HTTP status in the public contract.

Every error the widget can legitimately see is declared here, so the contract
in API.md can be read off this file. Anything else surfaces as a 500.
"""

from __future__ import annotations


class LivianaError(Exception):
    """Base class for errors with a defined place in the API contract."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class BadRequest(LivianaError):
    status_code = 400
    code = "bad_request"


class RateLimited(LivianaError):
    """Too many messages from one session inside the current minute."""

    status_code = 429
    code = "rate_limited"


class BudgetExhausted(LivianaError):
    """The daily invocation circuit breaker is open."""

    status_code = 503
    code = "budget_exhausted"


class UpstreamError(LivianaError):
    """The model backend failed or timed out."""

    status_code = 502
    code = "upstream_error"
