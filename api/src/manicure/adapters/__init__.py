"""Adapter registry.

Adapters are checked in registration order; the first whose
``matches(flow)`` returns True wins.
"""

from __future__ import annotations

from typing import Any  # Any: mitmproxy flow object, untyped

from manicure.adapters.anthropic import AnthropicAdapter
from manicure.adapters.base import ProviderAdapter

_adapters: list[ProviderAdapter] = [
    AnthropicAdapter(),
]


def get_adapter(flow: Any) -> ProviderAdapter | None:  # Any: mitmproxy flow object
    """Return the first adapter whose ``matches(flow)`` is True, or None."""
    for adapter in _adapters:
        if adapter.matches(flow):
            return adapter
    return None


__all__ = ["ProviderAdapter", "get_adapter"]
