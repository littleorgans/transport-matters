from typing import TYPE_CHECKING, cast

from transport_matters import exchange_recorder as recorder
from transport_matters._exchange_recorder_http_support import (
    _Flow,
    _make_response_body,
    _make_state,
    _Response,
    _SeqCounter,
)
from transport_matters.storage import (
    ExchangeArtifacts,
    IndexEntry,
    StorageBackend,
    get_storage,
)

if TYPE_CHECKING:
    import pytest
    from mitmproxy import http

    from transport_matters.flow_state import RequestFlowState

pytest_plugins = ("transport_matters._exchange_recorder_http_fixtures",)


async def test_persist_http_exchange_deletes_when_request_state_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(provisional_exchange_id="exchange-drop")
    state.dropped = True
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).response = _Response(_make_response_body())
    calls: list[tuple[http.HTTPFlow, RequestFlowState]] = []

    async def fake_delete(
        delete_flow: http.HTTPFlow,
        delete_state: RequestFlowState,
    ) -> bool:
        calls.append((delete_flow, delete_state))
        return True

    async def fail_finalize(*args: object) -> bool:
        raise AssertionError("drop path must not finalize")

    async def fail_persist(
        storage: StorageBackend,
        entry: IndexEntry,
        artifacts: ExchangeArtifacts,
    ) -> bool:
        raise AssertionError("drop path must not create a fallback exchange")

    monkeypatch.setattr(recorder, "_delete_http_provisional_exchange", fake_delete)
    monkeypatch.setattr(recorder, "_finalize_http_provisional_exchange", fail_finalize)
    monkeypatch.setattr(recorder, "_persist_exchange", fail_persist)

    persisted = await recorder._persist_http_exchange(flow, state, None)

    assert persisted is True
    assert calls == [(flow, state)]


async def test_persist_http_exchange_drop_without_provisional_skips_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state()
    state.dropped = True
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).response = _Response(_make_response_body())
    calls: list[tuple[http.HTTPFlow, RequestFlowState]] = []

    async def fake_delete(
        delete_flow: http.HTTPFlow,
        delete_state: RequestFlowState,
    ) -> bool:
        calls.append((delete_flow, delete_state))
        return True

    async def fail_persist(
        storage: StorageBackend,
        entry: IndexEntry,
        artifacts: ExchangeArtifacts,
    ) -> bool:
        raise AssertionError("drop path must not create a fallback exchange")

    monkeypatch.setattr(recorder, "_delete_http_provisional_exchange", fake_delete)
    monkeypatch.setattr(recorder, "_persist_exchange", fail_persist)

    persisted = await recorder._persist_http_exchange(flow, state, None)

    assert persisted is True
    assert calls == [(flow, state)]


async def test_persist_http_exchange_finalizes_existing_provisional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(provisional_exchange_id="exchange-finalize")
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).response = _Response(_make_response_body())
    counter = _SeqCounter([1, 2])
    calls: list[tuple[http.HTTPFlow, RequestFlowState, object | None]] = []

    async def fake_finalize(
        finalize_flow: http.HTTPFlow,
        finalize_state: RequestFlowState,
        token_counter: object | None,
    ) -> bool:
        calls.append((finalize_flow, finalize_state, token_counter))
        return True

    async def fail_persist(
        storage: StorageBackend,
        entry: IndexEntry,
        artifacts: ExchangeArtifacts,
    ) -> bool:
        raise AssertionError("finalized provisional must not create duplicate row")

    monkeypatch.setattr(recorder, "_finalize_http_provisional_exchange", fake_finalize)
    monkeypatch.setattr(recorder, "_persist_exchange", fail_persist)

    persisted = await recorder._persist_http_exchange(flow, state, counter)

    assert persisted is True
    assert calls == [(flow, state, counter)]


async def test_persist_http_exchange_falls_back_when_finalize_misses_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(provisional_exchange_id="exchange-missing")
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).response = _Response(_make_response_body())
    calls: list[tuple[http.HTTPFlow, RequestFlowState, object | None]] = []

    async def fake_finalize(
        finalize_flow: http.HTTPFlow,
        finalize_state: RequestFlowState,
        token_counter: object | None,
    ) -> bool:
        calls.append((finalize_flow, finalize_state, token_counter))
        return False

    monkeypatch.setattr(recorder, "_finalize_http_provisional_exchange", fake_finalize)

    persisted = await recorder._persist_http_exchange(flow, state, None)

    assert persisted is True
    assert calls == [(flow, state, None)]
    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    assert entries[0].id != "exchange-missing"
    assert entries[0].res is not None
