"""Tests for the adapter registry (get_adapter)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from manicure.adapters import get_adapter
from manicure.exceptions import UnsupportedProviderError


class TestGetAdapter:
    def test_raises_unsupported_provider_for_unknown_host(self) -> None:
        """get_adapter raises UnsupportedProviderError when no adapter matches."""
        flow = MagicMock()
        flow.request.path = "/v1/completions"
        flow.request.host = "unknown.example.com"

        with pytest.raises(UnsupportedProviderError) as exc_info:
            get_adapter(flow)

        assert "No adapter matches" in str(exc_info.value)

    def test_returns_adapter_for_anthropic_flow(self) -> None:
        """Anthropic adapter matches /v1/messages paths."""
        flow = MagicMock()
        flow.request.path = "/v1/messages"
        flow.request.host = "api.anthropic.com"

        adapter = get_adapter(flow)
        assert adapter.name == "anthropic"

    def test_exception_has_detail_attribute(self) -> None:
        """UnsupportedProviderError carries a detail message."""
        flow = MagicMock()
        flow.request.path = "/v1/other"
        flow.request.host = "unknown.test"

        with pytest.raises(UnsupportedProviderError) as exc_info:
            get_adapter(flow)

        assert exc_info.value.detail is not None
        assert "unknown.test" in exc_info.value.detail
