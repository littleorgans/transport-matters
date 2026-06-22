from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from transport_matters import config
from transport_matters.api.v1 import run_routes
from transport_matters.api.v1.session_store import (
    optional_session_pool as _ORIGINAL_OPTIONAL_SESSION_POOL,
)
from transport_matters.main import create_app
from transport_matters.test_run_manager import (
    PreparedRunHarness,
    PtyHarness,
    make_manager,
    patch_pty_teardown,
    resolved_worktree,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from fastapi import Request

    from transport_matters.captured_run import (
        CapturedRunLease,
        CapturedRunRequest,
        CapturedRunSpawnSpec,
    )
    from transport_matters.space.models import ResolvedWorktree, WorktreeId

BACKEND_ORIGIN = "http://localhost:8788"


class _FakePoolConnection:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakePool:
    def connection(self) -> _FakePoolConnection:
        return _FakePoolConnection()


def _install_space_store(
    monkeypatch: pytest.MonkeyPatch,
    resolved: ResolvedWorktree,
) -> ResolvedWorktree:
    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def resolve_worktree(
            self, requested: WorktreeId, *, owner: str = "local"
        ) -> ResolvedWorktree | None:
            assert owner == "local"
            if requested != resolved.worktree_id:
                return None
            return resolved

    def optional_session_pool(request: Request) -> object:
        return _ORIGINAL_OPTIONAL_SESSION_POOL(request) or _FakePool()

    monkeypatch.setattr(run_routes, "SpaceStore", Store, raising=False)
    monkeypatch.setattr(run_routes, "optional_session_pool", optional_session_pool)
    return resolved


class ManagedRunHarness:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.pty = PtyHarness()
        patch_pty_teardown(monkeypatch, self.pty)
        self.prepared = PreparedRunHarness(tmp_path)
        self.resolved = _install_space_store(monkeypatch, resolved_worktree(tmp_path))
        self.space_id = self.resolved.space_id
        self.worktree_id = self.resolved.worktree_id

        async def prepare_shared(
            request: CapturedRunRequest,
            **_: object,
        ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
            return self.prepared.prepare(request)

        monkeypatch.setattr(
            "transport_matters.run_manager.prepare_shared_captured_run",
            prepare_shared,
        )
        self.manager = make_manager(
            tmp_path,
            self.pty,
            self.prepared,
            shared_proxy_manager=object(),
        )
        monkeypatch.setattr(run_routes, "create_run_manager", lambda **_: self.manager)

    def body(self, harness: str = "claude", **extra: object) -> dict[str, object]:
        return {"harness": harness, "worktreeId": str(self.worktree_id), **extra}


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    config.get_settings.cache_clear()
    return TestClient(create_app())


def _http_headers(origin: str, *, host: str = "localhost:8788") -> dict[str, str]:
    return {"origin": origin, "host": host}


def _websocket_headers(origin: str, *, host: str = "localhost:8788") -> dict[str, str]:
    return {"origin": origin, "host": host}
