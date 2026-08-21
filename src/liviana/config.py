"""Runtime configuration.

Nothing in this file (or anywhere else under ``src/``) is specific to a
client. Infrastructure names come from the Lambda environment variables and
every piece of client content comes from the JSON document in S3. Deploying
Liviana for another client means a new bucket, a new content JSON and a new set
of environment variables, with no code change.

Two backends exist and are selected with ``LIVIANA_BACKEND``:

  mock  local JSON files, no AWS account needed (phase 1, terminal testing)
  aws   S3 + DynamoDB + Bedrock (production)

The required variables differ per backend, so validation happens after the
backend is known.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_MOCK = "mock"
BACKEND_AWS = "aws"

# Repository root, used only to resolve the default paths of the mock backend.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """Raised when the environment is missing or malforming a setting."""


def _optional(name: str, fallback: str) -> str:
    value = os.environ.get(name)
    return fallback if value is None or value == "" else value


def _required(name: str, backend: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"Missing required environment variable {name} "
            f"(backend={backend}). See .env.example."
        )
    return value


def _number(name: str, fallback: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return fallback
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from exc


def _integer(name: str, fallback: int) -> int:
    value = _number(name, fallback)
    if value != int(value):
        raise ConfigError(f"{name} must be a whole number, got {value!r}.")
    return int(value)


@dataclass(frozen=True)
class Config:
    backend: str
    region: str

    # --- Content (S3 in aws, a local file in mock) ---
    content_bucket: str
    content_key: str
    content_path: str
    content_cache_ttl_s: int

    # --- State (two DynamoDB tables in aws, one local JSON file in mock) ---
    conversations_table: str
    limits_table: str
    state_path: str

    # --- Model ---
    model_id: str
    max_tokens: int
    temperature: float

    # --- Conversation memory ---
    history_pairs: int
    conversation_ttl_hours: int

    # --- Cost and abuse protection ---
    rate_limit_per_minute: int
    daily_invocation_limit: int
    max_message_chars: int

    # --- HTTP ---
    allowed_origin: str

    @property
    def is_mock(self) -> bool:
        return self.backend == BACKEND_MOCK

    @property
    def conversation_ttl_seconds(self) -> int:
        return self.conversation_ttl_hours * 3600


def load_config() -> Config:
    backend = _optional("LIVIANA_BACKEND", BACKEND_AWS).strip().lower()
    if backend not in (BACKEND_MOCK, BACKEND_AWS):
        raise ConfigError(
            f"LIVIANA_BACKEND must be {BACKEND_MOCK!r} or {BACKEND_AWS!r}, "
            f"got {backend!r}."
        )
    mock = backend == BACKEND_MOCK

    # AWS_REGION is injected by the Lambda runtime; LIVIANA_REGION overrides it
    # when the table, the bucket or the Bedrock endpoint live somewhere else.
    region = _optional("LIVIANA_REGION", os.environ.get("AWS_REGION") or "eu-central-1")

    default_content_path = str(_REPO_ROOT / "content" / "content.json")
    default_state_path = str(_REPO_ROOT / ".liviana-state.json")

    return Config(
        backend=backend,
        region=region,
        content_bucket="" if mock else _required("LIVIANA_CONTENT_BUCKET", backend),
        content_key=_optional("LIVIANA_CONTENT_KEY", "content.json"),
        content_path=_optional("LIVIANA_CONTENT_PATH", default_content_path),
        content_cache_ttl_s=_integer("LIVIANA_CONTENT_CACHE_TTL_S", 300),
        conversations_table=(
            "" if mock else _required("LIVIANA_CONVERSATIONS_TABLE", backend)
        ),
        limits_table="" if mock else _required("LIVIANA_LIMITS_TABLE", backend),
        state_path=_optional("LIVIANA_STATE_PATH", default_state_path),
        model_id=(
            _optional("LIVIANA_MODEL_ID", "mock-model")
            if mock
            else _required("LIVIANA_MODEL_ID", backend)
        ),
        max_tokens=_integer("LIVIANA_MAX_TOKENS", 400),
        temperature=_number("LIVIANA_TEMPERATURE", 0.2),
        history_pairs=_integer("LIVIANA_HISTORY_PAIRS", 4),
        conversation_ttl_hours=_integer("LIVIANA_CONVERSATION_TTL_HOURS", 24),
        rate_limit_per_minute=_integer("LIVIANA_RATE_LIMIT_PER_MINUTE", 20),
        daily_invocation_limit=_integer("LIVIANA_DAILY_INVOCATION_LIMIT", 500),
        max_message_chars=_integer("LIVIANA_MAX_MESSAGE_CHARS", 1000),
        allowed_origin=_optional("LIVIANA_ALLOWED_ORIGIN", "*"),
    )
