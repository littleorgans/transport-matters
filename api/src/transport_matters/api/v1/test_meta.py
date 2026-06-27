"""Tests for the meta endpoint."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters import config
from transport_matters.api.v1 import meta as meta_module
from transport_matters.main import create_app
from transport_matters.test_run_manager import resolved_worktree
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from transport_matters.space.models import ResolvedWorktree


class _FakePoolConnection:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakePool:
    def connection(self) -> _FakePoolConnection:
        return _FakePoolConnection()


def _install_cwd_store(
    monkeypatch: pytest.MonkeyPatch,
    resolved: ResolvedWorktree | Exception,
) -> None:
    """Stub the meta endpoint's cwd -> worktree resolution.

    Pass a ``ResolvedWorktree`` for the happy path or an ``Exception`` to assert
    the best-effort fallback (meta stays 200 with null space/worktree).
    """

    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def resolve_session_cwd(self, cwd: str, *, owner: str = "local") -> ResolvedWorktree:
            assert owner == "local"
            if isinstance(resolved, Exception):
                raise resolved
            return resolved

    monkeypatch.setattr(meta_module, "SpaceStore", Store, raising=False)
    monkeypatch.setattr(meta_module, "optional_session_pool", lambda _request: _FakePool())


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
        assert set(data.keys()) == {
            "channel",
            "channel_badge",
            "channel_label",
            "cwd",
            "workspace_id",
            "run_id",
            "space_id",
            "worktree_id",
            "harnesses",
            "transcript_denylist",
        }
        assert data["channel"] == "stable"
        assert data["channel_label"] == "Stable"
        assert data["channel_badge"] is None
        assert isinstance(data["cwd"], str)
        assert isinstance(data["workspace_id"], str)
        assert data["run_id"] is None
        assert isinstance(data["harnesses"], list)
        assert isinstance(data["transcript_denylist"], list)

    async def test_transcript_denylist_defaults_empty(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # No file on disk under the storage root -> reveal-all (empty denylist).
        monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(tmp_path))
        config.get_settings.cache_clear()
        response = await client.get("/api/meta")
        assert response.json()["transcript_denylist"] == []

    async def test_transcript_denylist_echoes_file(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The endpoint echoes the operator-edited file verbatim so the UI can apply it.
        monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(tmp_path))
        config.get_settings.cache_clear()
        (tmp_path / "transcript_denylist.json").write_text(
            json.dumps({"hide": [{"path": "attachment.type", "equals": "output_style"}]}),
            encoding="utf-8",
        )
        response = await client.get("/api/meta")
        assert response.json()["transcript_denylist"] == [
            {"path": "attachment.type", "equals": "output_style"}
        ]

    async def test_preview_channel_meta_fields(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRANSPORT_MATTERS_CHANNEL", "preview")
        config.get_settings.cache_clear()
        response = await client.get("/api/meta")
        data = response.json()
        assert data["channel"] == "preview"
        assert data["channel_label"] == "Preview"
        assert data["channel_badge"] == {
            "text": "PREVIEW",
            "color": "amber",
            "hex": "#f59e0b",
        }

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

    async def test_run_scoped_meta_uses_run_metadata(self, client: AsyncClient) -> None:
        response = await client.get("/v1/runs/run-current/meta")
        assert response.status_code == 200
        data = response.json()
        cwd = Path(data["cwd"])
        wid = workspace_id(cwd)
        assert data["run_id"] == "run-current"
        assert cwd.name == "workspace"
        assert data["workspace_id"] == f"{wid.slug}/{wid.hash}"

    async def test_space_and_worktree_null_without_session_store(self, client: AsyncClient) -> None:
        # The test app runs no lifespan, so app.state.session_pool is unset. Meta must
        # stay usable and report no default worktree rather than failing the launch.
        data = (await client.get("/api/meta")).json()
        assert data["space_id"] is None
        assert data["worktree_id"] is None

    async def test_space_and_worktree_resolved_from_cwd(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # With a session store the launch cwd resolves to its Space + primary worktree,
        # so the canvas has a default spawn target (POST /v1/runs requires one).
        resolved = resolved_worktree(tmp_path)
        _install_cwd_store(monkeypatch, resolved)
        data = (await client.get("/api/meta")).json()
        assert data["space_id"] == str(resolved.space_id)
        assert data["worktree_id"] == str(resolved.worktree_id)

    async def test_space_and_worktree_null_when_resolution_fails(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Resolution is best-effort: a store error must not 500 the launch.
        _install_cwd_store(monkeypatch, RuntimeError("boom"))
        response = await client.get("/api/meta")
        assert response.status_code == 200
        data = response.json()
        assert data["space_id"] is None
        assert data["worktree_id"] is None

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
