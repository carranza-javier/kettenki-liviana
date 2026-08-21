"""Content sources: a local file for the mock backend, S3 for production.

Both cache the parsed document for ``content_cache_ttl_s``. In Lambda that
cache survives across warm invocations, so a busy period costs one S3 GET every
few minutes instead of one per message.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..config import Config


def _validate(document: Any, origin: str) -> dict[str, Any]:
    """Fail loudly at load time rather than producing a confusing prompt."""
    if not isinstance(document, dict):
        raise ValueError(f"{origin}: content document must be a JSON object.")

    problems: list[str] = []
    if not document.get("identity", {}).get("assistant_name"):
        problems.append("identity.assistant_name is required")
    if not document.get("identity", {}).get("organisation"):
        problems.append("identity.organisation is required")

    sections = document.get("sections")
    if not isinstance(sections, list) or not sections:
        problems.append("sections must be a non-empty array")
    else:
        seen: set[str] = set()
        for section in sections:
            if not isinstance(section, dict) or not section.get("id"):
                problems.append(f"every section needs an id (got {section!r})")
                continue
            if section["id"] in seen:
                problems.append(f'duplicate section id "{section["id"]}"')
            seen.add(section["id"])
            if "data" not in section:
                problems.append(f'section "{section["id"]}" has no data')

    if problems:
        raise ValueError(f"{origin}: invalid content document: {'; '.join(problems)}")
    return document


class _CachedContent:
    def __init__(self, ttl_s: int) -> None:
        self._ttl_s = ttl_s
        self._value: dict[str, Any] | None = None
        self._loaded_at = 0.0

    def get(self) -> dict[str, Any]:
        if self._value is not None and time.time() - self._loaded_at < self._ttl_s:
            return self._value
        self._value = self._fetch()
        self._loaded_at = time.time()
        return self._value

    def _fetch(self) -> dict[str, Any]:  # pragma: no cover - overridden
        raise NotImplementedError


class LocalContentSource(_CachedContent):
    """Reads the content document straight off the filesystem."""

    def __init__(self, config: Config) -> None:
        super().__init__(config.content_cache_ttl_s)
        self._path = Path(config.content_path)

    def load(self) -> dict[str, Any]:
        return self.get()

    def _fetch(self) -> dict[str, Any]:
        raw = self._path.read_text(encoding="utf-8")
        return _validate(json.loads(raw), str(self._path))


class S3ContentSource(_CachedContent):
    """Reads the content document from the client's S3 bucket."""

    def __init__(self, config: Config) -> None:
        super().__init__(config.content_cache_ttl_s)
        import boto3  # imported lazily so the mock backend needs no boto3

        self._bucket = config.content_bucket
        self._key = config.content_key
        self._s3 = boto3.client("s3", region_name=config.region)

    def load(self) -> dict[str, Any]:
        return self.get()

    def _fetch(self) -> dict[str, Any]:
        response = self._s3.get_object(Bucket=self._bucket, Key=self._key)
        raw = response["Body"].read().decode("utf-8")
        return _validate(json.loads(raw), f"s3://{self._bucket}/{self._key}")
