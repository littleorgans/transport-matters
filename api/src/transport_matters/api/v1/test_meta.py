"""Tests for the meta endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters import config
from transport_matters.main import create_app
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    # ``get_settings`` is lru_cached; clear before each test so
    # TRANSPORT_MATTERS_* env changes take effect.
    config.get_settings.cache_clear()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestMeta:
    async def test_shape(self, client: AsyncClient) -> None:
        response = await client.get("/api/meta")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) == {"cwd", "workspace_id", "run_id", "harnesses"}
        assert isinstance(data["cwd"], str)
        assert isinstance(data["workspace_id"], str)
        assert data["run_id"] is None
        assert isinstance(data["harnesses"], list)

    async def test_cwd_falls_back_to_process_cwd_when_env_unset(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Direct uvicorn / test runs have no TRANSPORT_MATTERS_CWD — the endpoint
        # should fall back to ``Path.cwd().resolve()`` rather than 500.
        monkeypatch.delenv("TRANSPORT_MATTERS_CWD", raising=False)
        config.get_settings.cache_clear()
        response = await client.get("/api/meta")
        data = response.json()
        assert data["cwd"] == str(Path.cwd().resolve())

    async def test_cwd_respects_transport_matters_cwd_env(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Simulates ``transport-matters claude`` flowing TRANSPORT_MATTERS_CWD through.
        # The meta endpoint must honour it instead of Path.cwd(),
        # otherwise a mitmdump inheriting a subdirectory (e.g. api/)
        # leaks that path into project-scoped overlays.
        monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
        config.get_settings.cache_clear()
        response = await client.get("/api/meta")
        data = response.json()
        # Test assertion path resolve, not production async I/O.
        assert data["cwd"] == str(tmp_path.resolve())  # noqa: ASYNC240

    async def test_workspace_id_matches_helper(self, client: AsyncClient) -> None:
        response = await client.get("/api/meta")
        data = response.json()
        wid = workspace_id(Path.cwd())
        assert data["workspace_id"] == f"{wid.slug}/{wid.hash}"

    async def test_run_id_respects_env(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-123")
        config.get_settings.cache_clear()
        response = await client.get("/api/meta")
        data = response.json()
        assert data["run_id"] == "run-123"

    async def test_harnesses_expose_current_capabilities(self, client: AsyncClient) -> None:
        response = await client.get("/api/meta")
        data = response.json()
        harnesses = {harness["id"]: harness for harness in data["harnesses"]}

        assert set(harnesses) == {"claude", "codex"}

        claude = harnesses["claude"]
        assert claude["proxy_mode"] == "reverse"
        assert claude["trust_requirement"] == "none"
        base_capabilities = {
            "startup_probe": False,
            "disposable_probe": False,
            "overlay_before_work": False,
            "tool_schema_overlay": True,
            "provider_extras_controls": True,
            "replay": False,
            "fork": False,
            "transport_diagnostics": False,
            "codex_turn_telemetry": False,
            "websocket_artifacts": False,
            "http_fallback_artifacts": False,
        }
        assert list(claude["capabilities"]) == list(base_capabilities)
        assert claude["capabilities"] == base_capabilities

        codex = harnesses["codex"]
        assert codex["proxy_mode"] == "explicit"
        assert codex["trust_requirement"] == "codex_ca_certificate"
        codex_capabilities = base_capabilities | {
            "transport_diagnostics": True,
            "codex_turn_telemetry": True,
            "websocket_artifacts": True,
            "http_fallback_artifacts": True,
        }
        assert list(codex["capabilities"]) == list(codex_capabilities)
        assert codex["capabilities"] == codex_capabilities
