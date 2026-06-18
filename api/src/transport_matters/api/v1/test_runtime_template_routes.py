"""Tests for the runtime template browse endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters import env_keys

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from httpx import AsyncClient


async def test_runtime_templates_endpoint_response_shape(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    template = home / ".agent-runtimes" / "runtimes" / "research"
    template.mkdir(parents=True)
    (template / "runtime.toml").write_text("[runtime]\n", encoding="utf-8")
    (template / "capabilities.json").write_text(
        """
        {
          "schema_version": 2,
          "vendors": ["anthropic", "openai"],
          "required_capabilities": [],
          "recommended_model": {
            "default": {"harness": "claude", "vendor": "anthropic"},
            "by_vendor": {
              "anthropic": {"model": "claude-opus-4-8", "effort": "xhigh"},
              "openai": {"model": "gpt-5.5", "effort": "xhigh"}
            }
          },
          "generated_from": "digest"
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))

    response = await client.get("/v1/runtime-templates")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "name": "research",
                "vendors": ["anthropic", "openai"],
                "required_capabilities": [],
                "recommended_model": {
                    "default": {"harness": "claude", "vendor": "anthropic"},
                    "by_vendor": {
                        "anthropic": {"model": "claude-opus-4-8", "effort": "xhigh"},
                        "openai": {"model": "gpt-5.5", "effort": "xhigh"},
                    },
                },
            }
        ]
    }


async def test_runtime_templates_endpoint_missing_roots_returns_empty(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    transport_home = tmp_path / "tm-home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(env_keys.HOME, str(transport_home))

    response = await client.get("/v1/runtime-templates")

    assert response.status_code == 200
    assert response.json() == {"items": []}
