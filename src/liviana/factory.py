"""Wires the ports to the backend named by LIVIANA_BACKEND.

The service is built once per execution environment and reused, so a warm
Lambda keeps its boto3 clients and its cached content document instead of
rebuilding both on every message.
"""

from __future__ import annotations

from .config import Config, load_config
from .service import LivianaService

_cached: tuple[Config, LivianaService] | None = None


def build_service(config: Config | None = None) -> LivianaService:
    config = config or load_config()

    if config.is_mock:
        from .adapters.content import LocalContentSource
        from .adapters.local_store import LocalStore
        from .adapters.mock_model import MockModelClient

        content_source = LocalContentSource(config)
        # One file stands in for both tables.
        store = LocalStore(config.state_path)
        return LivianaService(
            config=config,
            content_source=content_source,
            conversations=store,
            limits=store,
            model=MockModelClient(content_source),
        )

    from .adapters.bedrock_model import BedrockModelClient
    from .adapters.content import S3ContentSource
    from .adapters.dynamo_store import DynamoConversationStore, DynamoLimitStore

    return LivianaService(
        config=config,
        content_source=S3ContentSource(config),
        conversations=DynamoConversationStore(config.conversations_table, config.region),
        limits=DynamoLimitStore(config.limits_table, config.region),
        model=BedrockModelClient(config.model_id, config.region),
    )


def get_service() -> tuple[Config, LivianaService]:
    """Process-wide singleton, rebuilt only on a cold start."""
    global _cached
    if _cached is None:
        config = load_config()
        _cached = (config, build_service(config))
    return _cached
