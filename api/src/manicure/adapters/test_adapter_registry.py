"""Tests for the adapter registry (get_adapter)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from manicure.adapters import get_adapter, get_adapter_for_provider
from manicure.exceptions import UnsupportedProviderError


@pytest.mark.parametrize("module_name", ["manicure.storage", "manicure.codex"])
def test_low_level_packages_import_cleanly_in_fresh_interpreter(
    module_name: str,
) -> None:
    """Regression for package-level cycles masked by pytest import order."""
    api_root = Path(__file__).resolve().parents[3]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(api_root / "src")
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", f"import {module_name}"],
        cwd=api_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr


class TestGetAdapter:
    def test_returns_adapter_for_provider_name(self) -> None:
        """Provider lookup still resolves the Codex adapter after import cleanup."""
        adapter = get_adapter_for_provider("codex")

        assert adapter.name == "codex"

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

    def test_returns_adapter_for_codex_websocket_flow(self) -> None:
        """Codex adapter matches the ChatGPT websocket transport."""
        flow = MagicMock()
        flow.request.path = "/backend-api/codex/responses?client=cli"
        flow.request.host = "chatgpt.com"

        adapter = get_adapter(flow)
        assert adapter.name == "codex"

    def test_exception_has_detail_attribute(self) -> None:
        """UnsupportedProviderError carries a detail message."""
        flow = MagicMock()
        flow.request.path = "/v1/other"
        flow.request.host = "unknown.test"

        with pytest.raises(UnsupportedProviderError) as exc_info:
            get_adapter(flow)

        assert exc_info.value.detail is not None
        assert "unknown.test" in exc_info.value.detail
