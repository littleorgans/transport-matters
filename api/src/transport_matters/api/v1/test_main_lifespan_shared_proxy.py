from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters.config import get_settings
from transport_matters.main import create_app, lifespan

if TYPE_CHECKING:
    from fastapi import FastAPI


class FakePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeListener:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeSharedProxyManager:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.closed = False
        self.fail_start = fail_start

    async def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("proxy failed")

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_lifespan_degrades_when_shared_proxy_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FakePool()
    manager = FakeSharedProxyManager(fail_start=True)

    async def start_session_store(app: FastAPI, _database_url: str) -> FakePool:
        app.state.session_pool = pool
        app.state.session_event_listener = None
        return pool

    monkeypatch.setattr(
        "transport_matters.main.resolve_database_url",
        lambda _settings: "postgresql://example/tm_test_shared_proxy",
    )
    monkeypatch.setattr("transport_matters.main._start_session_store", start_session_store)
    monkeypatch.setattr(
        "transport_matters.main.SharedProxyManager.create",
        lambda **_: manager,
    )
    get_settings.cache_clear()
    app = create_app()
    try:
        async with lifespan(app):
            assert app.state.shared_proxy_manager is None
            assert app.state.run_manager._shared_proxy_unavailable_reason == "proxy failed"
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health")
            assert response.status_code == 200
    finally:
        get_settings.cache_clear()

    assert manager.closed
    assert pool.closed


@pytest.mark.asyncio
async def test_lifespan_shutdown_closes_later_resources_after_close_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FakePool()
    listener = FakeListener()
    shared_proxy_manager = FakeSharedProxyManager()

    async def start_session_store(app: FastAPI, _database_url: str) -> FakePool:
        app.state.session_pool = pool
        app.state.session_event_listener = listener
        return pool

    async def close_run_manager(_app: FastAPI) -> None:
        raise RuntimeError("run manager close failed")

    monkeypatch.setattr(
        "transport_matters.main.resolve_database_url",
        lambda _settings: "postgresql://example/tm_test_shared_proxy",
    )
    monkeypatch.setattr("transport_matters.main._start_session_store", start_session_store)
    monkeypatch.setattr(
        "transport_matters.main.SharedProxyManager.create",
        lambda **_: shared_proxy_manager,
    )
    monkeypatch.setattr(
        "transport_matters.main.run_routes.create_run_manager",
        lambda **_: object(),
    )
    monkeypatch.setattr(
        "transport_matters.main.run_routes.close_run_manager",
        close_run_manager,
    )
    get_settings.cache_clear()
    app = create_app()
    try:
        async with lifespan(app):
            pass
    finally:
        get_settings.cache_clear()

    assert shared_proxy_manager.closed
    assert listener.closed
    assert pool.closed
