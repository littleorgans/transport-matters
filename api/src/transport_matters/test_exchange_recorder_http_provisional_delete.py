import json
from typing import TYPE_CHECKING, cast

from transport_matters import broadcast
from transport_matters import exchange_recorder as recorder
from transport_matters._exchange_recorder_http_support import _Flow, _make_state
from transport_matters.storage import get_storage

if TYPE_CHECKING:
    import pytest
    from mitmproxy import http

pytest_plugins = ("transport_matters._exchange_recorder_http_fixtures",)


async def test_delete_http_provisional_exchange_removes_pending_row_and_broadcasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state()
    flow = cast("http.HTTPFlow", _Flow())
    exchange_id = await recorder.persist_http_provisional_exchange(flow, state)

    assert exchange_id is not None
    state.provisional_exchange_id = exchange_id
    storage = await get_storage()
    assert await storage.read_index_entry(exchange_id) is not None
    events = broadcast.subscribe("run-http")
    deleted_calls: list[tuple[str, str, str | None]] = []
    emit_deleted = recorder.emit_exchange_deleted

    def spy_emit_deleted(deleted_id: str, *, run_id: str, flow_id: str | None = None) -> None:
        deleted_calls.append((deleted_id, run_id, flow_id))
        emit_deleted(deleted_id, run_id=run_id, flow_id=flow_id)

    monkeypatch.setattr(recorder, "emit_exchange_deleted", spy_emit_deleted)

    deleted = await recorder.delete_http_provisional_exchange(flow, state)

    assert deleted is True
    assert state.provisional_exchange_id is None
    assert await storage.read_index_entry(exchange_id) is None
    delete_event = json.loads(events.get_nowait())
    assert delete_event == {
        "type": "exchange_deleted",
        "id": exchange_id,
        "run_id": "run-http",
        "flow_id": flow.id,
    }
    assert deleted_calls == [(exchange_id, "run-http", flow.id)]

    deleted_again = await recorder.delete_http_provisional_exchange(flow, state)

    assert deleted_again is True
    assert events.empty()
    assert deleted_calls == [(exchange_id, "run-http", flow.id)]


async def test_delete_http_provisional_exchange_returns_false_on_storage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(provisional_exchange_id="exchange-fail")
    flow = cast("http.HTTPFlow", _Flow())
    events = broadcast.subscribe("run-http")
    storage = await get_storage()

    async def raise_delete(exchange_id: str) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(storage, "delete_exchange", raise_delete)

    deleted = await recorder.delete_http_provisional_exchange(flow, state)

    assert deleted is False
    assert state.provisional_exchange_id == "exchange-fail"
    assert events.empty()
