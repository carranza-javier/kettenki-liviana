"""Bedrock model client, via the Converse API.

Converse rather than InvokeModel: it takes system prompt and message history as
first-class arguments and keeps the same shape across model families, so
swapping Claude Haiku for a cheaper model is an environment variable change
rather than a rewrite of the request body.

Timeouts are deliberately short. A visitor staring at a typing indicator will
give up long before botocore's 60 second default does, and an invocation that
is going to be abandoned should not keep a Lambda (and its reserved
concurrency slot) busy.
"""

from __future__ import annotations

import re

from ..errors import UpstreamError

_MARKDOWN_PATTERNS = [
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"\1"),
    (re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", re.S), r"\1"),
    (re.compile(r"^#{1,6}\s+", re.M), ""),
    (re.compile(r"^```.*$", re.M), ""),
]


def strip_markdown(text: str) -> str:
    """The widget renders plain text; rule 7 asks the model for plain text.

    Models drift anyway, so the formatting is removed here as well rather than
    letting stray asterisks reach the bubble.
    """
    for pattern, replacement in _MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()


class BedrockModelClient:
    def __init__(self, model_id: str, region: str) -> None:
        import boto3
        from botocore.config import Config as BotoConfig
        from botocore.exceptions import BotoCoreError, ClientError

        self._model_id = model_id
        self._errors = (BotoCoreError, ClientError)
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=BotoConfig(
                connect_timeout=3,
                read_timeout=20,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        try:
            response = self._client.converse(
                modelId=self._model_id,
                system=[{"text": system_prompt}],
                messages=[
                    {"role": message["role"], "content": [{"text": message["content"]}]}
                    for message in messages
                ],
                inferenceConfig={
                    "maxTokens": max_tokens,
                    "temperature": temperature,
                },
            )
        except self._errors as exc:
            raise UpstreamError(f"Bedrock call failed: {exc}") from exc

        try:
            blocks = response["output"]["message"]["content"]
            text = "".join(block.get("text", "") for block in blocks)
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("Bedrock returned an unexpected payload.") from exc

        if not text.strip():
            raise UpstreamError("Bedrock returned an empty answer.")
        return strip_markdown(text)
