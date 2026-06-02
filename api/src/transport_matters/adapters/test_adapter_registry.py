"""Tests for the adapter registry (get_adapter)."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from transport_matters.adapters import get_adapter, get_adapter_for_provider
from transport_matters.exceptions import UnsupportedProviderError


def _flow(
    path: str,
    host: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> MagicMock:
    flow = MagicMock()
    flow.request.path = path
    flow.request.host = host
    flow.request.method = method
    flow.request.headers = headers or {}
    return flow


@pytest.mark.parametrize("module_name", ["transport_matters.storage", "transport_matters.codex"])
def test_low_level_packages_import_cleanly_in_fresh_interpreter(
    module_name: str,
) -> None:
    """Regression for package-level cycles masked by pytest import order."""
    api_root = Path(__file__).resolve().parents[3]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(api_root / "src")
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=api_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr


class TestGetAdapter:
    @pytest.mark.parametrize(
        ("provider", "expected_adapter"),
        [("codex", "codex"), ("anthropic", "anthropic")],
    )
    def test_returns_adapter_for_provider_name(self, provider: str, expected_adapter: str) -> None:
        """Provider lookup is explicit wire adapter lookup by provider name."""
        adapter = get_adapter_for_provider(provider)

        assert adapter.name == expected_adapter

    def test_provider_lookup_rejects_launch_client_name(self) -> None:
        """Executable client names are not provider adapter names."""
        with pytest.raises(UnsupportedProviderError) as exc_info:
            get_adapter_for_provider("claude-code")

        assert "No adapter registered for claude-code" in str(exc_info.value)

    def test_raises_unsupported_provider_for_unknown_host(self) -> None:
        """get_adapter raises UnsupportedProviderError when no adapter matches."""
        flow = _flow("/v1/completions", "unknown.example.com")

        with pytest.raises(UnsupportedProviderError) as exc_info:
            get_adapter(flow)

        assert "No adapter matches" in str(exc_info.value)

    def test_returns_adapter_for_anthropic_flow(self) -> None:
        """Anthropic adapter matches /v1/messages paths."""
        flow = _flow("/v1/messages", "api.anthropic.com")

        adapter = get_adapter(flow)
        assert adapter.name == "anthropic"

    def test_returns_adapter_for_codex_websocket_flow(self) -> None:
        """Codex adapter matches the ChatGPT websocket transport."""
        flow = _flow("/backend-api/codex/responses?client=cli", "chatgpt.com")

        adapter = get_adapter(flow)
        assert adapter.name == "codex"

    def test_returns_adapter_for_codex_http_fallback_post_flow(self) -> None:
        """Codex HTTP fallback POST flows stay on Codex before Anthropic."""
        flow = _flow(
            "/backend-api/codex/responses?client=cli",
            "chatgpt.com",
            method="POST",
        )

        adapter = get_adapter(flow)
        assert adapter.name == "codex"

    def test_flow_selection_and_ir_provider_ignore_launch_client_name(self) -> None:
        """Provider identity comes from wire flow and adapter parsing."""
        flow = _flow(
            "/backend-api/codex/responses?client=claude-code",
            "chatgpt.com",
            method="POST",
        )
        adapter = get_adapter(flow)

        request_ir = adapter.inbound_request(b'{"type":"response.create","model":"gpt-5-codex"}')

        assert adapter.name == "codex"
        assert request_ir.provider == "codex"

    def test_exception_has_detail_attribute(self) -> None:
        """UnsupportedProviderError carries a detail message."""
        flow = _flow("/v1/other", "unknown.test")

        with pytest.raises(UnsupportedProviderError) as exc_info:
            get_adapter(flow)

        assert exc_info.value.detail is not None
        assert "unknown.test" in exc_info.value.detail
