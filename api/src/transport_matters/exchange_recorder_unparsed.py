"""Synthetic IR helpers for unparsed exchange recording."""

import json
from typing import Any

from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)


def _unparsed_model(raw: bytes, adapter_name: str) -> str:
    """Best-effort model from the raw JSON body, with a stable fallback."""
    try:
        decoded = json.loads(raw)
    except Exception:
        return f"{adapter_name}/unparsed"
    model = decoded.get("model") if isinstance(decoded, dict) else None
    return model if isinstance(model, str) and model else f"{adapter_name}/unparsed"


def _unparsed_request_ir(
    raw: bytes,
    adapter_name: str,
    client_version: str | None,
) -> InternalRequest:
    """Fabricate a synthetic IR marking a request we could not parse."""
    provider_extras: dict[str, Any] = {"type": "transport.parse_failure"}
    if client_version is not None:
        provider_extras["client_version"] = client_version
    return InternalRequest(
        model=_unparsed_model(raw, adapter_name),
        provider=adapter_name,
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="[unparsed request]")])],
        sampling=SamplingParams(max_tokens=0),
        metadata=RequestMetadata(),
        provider_extras=provider_extras,
    )
