"""Adapter registry.

Adapters are checked in registration order; the first whose
``matches(flow)`` returns True wins.
"""

from __future__ import annotations

from typing import Any  # Any: mitmproxy flow object, untyped

from manicure.adapters.anthropic import AnthropicAdapter
from manicure.adapters.base import ProviderAdapter
from manicure.codex.adapter import CodexAdapter
from manicure.exceptions import UnsupportedProviderError

_adapters: list[ProviderAdapter] = [
    CodexAdapter(),
    AnthropicAdapter(),
]


def get_adapter(flow: Any) -> ProviderAdapter:  # Any: mitmproxy flow object
    """Return the first adapter whose ``matches(flow)`` is True.

    Raises ``UnsupportedProviderError`` when no adapter matches.
    """
    for adapter in _adapters:
        if adapter.matches(flow):
            return adapter
    raise UnsupportedProviderError(
        detail=f"No adapter matches request to {getattr(flow.request, 'host', '?')}"
    )


def get_adapter_for_provider(provider: str) -> ProviderAdapter:
    """Return the adapter registered for an IR provider name."""
    for adapter in _adapters:
        if adapter.name == provider:
            return adapter
    raise UnsupportedProviderError(detail=f"No adapter registered for {provider}")


__all__ = [
    "ProviderAdapter",
    "UnsupportedProviderError",
    "get_adapter",
    "get_adapter_for_provider",
]
