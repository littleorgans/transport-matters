from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters import breakpoint as bp
from transport_matters.main import create_app
from transport_matters.override_state import scope_from_params
from transport_matters.overrides import get_store
from transport_matters.shared_proxy.manager import SharedProxyManager
from transport_matters.shared_proxy.models import SetOverridesRequest
from transport_matters.shared_proxy.test_manager import FakeControl, FakeProcess, make_binding

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    bp.disarm()
    bp._paused.clear()
    store = get_store()
    store.clear()
    store.enabled = True
    yield
    bp.disarm()
    bp._paused.clear()
    store.clear()
    store.enabled = True


@pytest.fixture
async def app_client(tmp_path: Path) -> AsyncGenerator[tuple[AsyncClient, FakeControl]]:
    app = create_app()
    control = FakeControl()
    manager = SharedProxyManager(
        process=FakeProcess(),
        control=control,
        monitor_interval_s=None,
    )
    await manager.register(make_binding(tmp_path, run_id="run-1", port=19001))
    app.state.shared_proxy_manager = manager
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, control


@pytest.mark.asyncio
async def test_patch_for_registered_run_forwards_snapshot(
    app_client: tuple[AsyncClient, FakeControl],
) -> None:
    client, control = app_client

    response = await client.patch(
        "/api/overrides?run_id=run-1",
        json={
            "overrides": [
                {
                    "kind": "system_part_toggle",
                    "target": "system:0",
                    "value": False,
                }
            ]
        },
    )

    assert response.status_code == 200
    requests = [request for request in control.requests if isinstance(request, SetOverridesRequest)]
    assert len(requests) == 1
    forwarded = requests[0]
    assert forwarded.scope.run_id == "run-1"
    assert forwarded.payload.enabled is True
    assert len(forwarded.payload.overrides) == 1
    assert forwarded.payload.overrides[0].target == "system:0"


@pytest.mark.asyncio
async def test_patch_rolls_back_local_store_when_forwarding_fails(
    app_client: tuple[AsyncClient, FakeControl],
) -> None:
    client, control = app_client
    control.fail_set_override_requests = 1

    response = await client.patch(
        "/api/overrides?run_id=run-1",
        json={
            "overrides": [
                {
                    "kind": "system_part_toggle",
                    "target": "system:0",
                    "value": False,
                }
            ]
        },
    )

    assert response.status_code == 500
    assert get_store().get_all(scope=scope_from_params("run-1", None)) == []
