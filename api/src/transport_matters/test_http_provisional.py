import asyncio
import json
from typing import TYPE_CHECKING, Any, cast

import pytest
from mitmproxy import http
from mitmproxy.test import tflow

from transport_matters import addon_handlers, broadcast
from transport_matters import breakpoint as bp
from transport_matters.addon import TransportMattersAddon
from transport_matters.config import get_settings
from transport_matters.flow_state import (
    get_request_flow_state,
    update_request_flow_state,
)
from transport_matters.ir import (
    Message,
    SystemPart,
    TextBlock,
)
from transport_matters.overrides import OverrideAudit, get_store
from transport_matters.storage import get_storage, init_storage, reset_storage
from transport_matters.track_manager import get_track_manager

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from transport_matters.counting import TokenCountingClient
    from transport_matters.flow_state import RequestFlowState
    from transport_matters.ir import InternalRequest, InternalResponse
    from transport_matters.storage.base import IndexEntry
    from transport_matters.track_manager import TrackAssignment


class _SeqCounter:
    def __init__(self, values: list[int | None]) -> None:
        self._iter = iter(values)
        self.calls = 0
        self.payloads: list[bytes] = []
        self.auth_headers: list[dict[str, str]] = []

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
        self.calls += 1
        self.payloads.append(payload)
        self.auth_headers.append(auth_headers)
        return next(self._iter)


@pytest.fixture(autouse=True)
def _reset_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    broadcast._subscribers.clear()
    broadcast._next_id = 0
    bp.disarm()
    bp._paused.clear()
    reset_storage()
    init_storage(root=tmp_path)
    store = get_store()
    store.clear()
    store.enabled = True
    get_track_manager()._runs.clear()
    monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-http")
    get_settings.cache_clear()
    yield
    broadcast._subscribers.clear()
    broadcast._next_id = 0
    bp.disarm()
    bp._paused.clear()
    reset_storage()
    store.clear()
    store.enabled = True
    get_track_manager()._runs.clear()
    get_settings.cache_clear()


def _request_body(
    *,
    model: str = "claude-3-5-sonnet",
    system_text: str = "original system",
    message_text: str = "hello",
) -> dict[str, object]:
    return {
        "model": model,
        "system": [{"type": "text", "text": system_text}],
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": message_text}],
            }
        ],
    }


def _response_body(
    *,
    text: str = "final text",
    stop_reason: str = "end_turn",
) -> dict[str, object]:
    return {
        "id": "msg_http",
        "type": "message",
        "role": "assistant",
        "model": "claude-3-5-sonnet",
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": 25,
            "output_tokens": 150,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 5,
        },
        "content": [{"type": "text", "text": text}],
    }


def _http_flow(
    flow_id: str,
    *,
    model: str = "claude-3-5-sonnet",
    system_text: str = "original system",
    message_text: str = "hello",
) -> http.HTTPFlow:
    flow = tflow.tflow()
    flow.id = flow_id
    flow.request.host = "api.anthropic.com"
    flow.request.scheme = "https"
    flow.request.method = "POST"
    flow.request.path = "/v1/messages"
    flow.request.headers["content-type"] = "application/json"
    flow.request.headers["x-api-key"] = "test-key"
    flow.request.set_text(
        json.dumps(
            _request_body(
                model=model,
                system_text=system_text,
                message_text=message_text,
            )
        )
    )
    flow.response = None
    return flow


def _set_response(
    flow: http.HTTPFlow,
    body: dict[str, object],
    *,
    status_code: int = 200,
) -> None:
    flow.response = http.Response.make(
        status_code,
        json.dumps(body).encode(),
        {"content-type": "application/json"},
    )


def _audit() -> OverrideAudit:
    return OverrideAudit(entries=[], chars_before=100, chars_after=80)


def _curated_ir(
    ir: InternalRequest,
    *,
    system_text: str = "curated system",
    message_text: str | None = None,
) -> InternalRequest:
    updates: dict[str, object] = {"system": [SystemPart(text=system_text)]}
    if message_text is not None:
        updates["messages"] = [Message(role="user", content=[TextBlock(text=message_text)])]
    return ir.model_copy(update=updates)


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    system_text: str = "curated system",
    message_text: str | None = None,
) -> None:
    async def fake_run_pipeline(
        ir: InternalRequest,
        flow_id: str,
        run_id: str | None,
    ) -> tuple[InternalRequest, OverrideAudit, None]:
        return (
            _curated_ir(ir, system_text=system_text, message_text=message_text),
            (_audit()),
            None,
        )

    monkeypatch.setattr(addon_handlers, "run_pipeline", fake_run_pipeline)


def _event(queue: asyncio.Queue[str]) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(queue.get_nowait()))


async def _wait_event(queue: asyncio.Queue[str]) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(await asyncio.wait_for(queue.get(), 0.2)))


async def _wait_for_pause(flow_id: str) -> None:
    for _ in range(200):
        if flow_id in await bp.get_paused():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("flow never paused")


async def _single_entry() -> IndexEntry:
    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    return entries[0]


async def _request_pending(
    flow: http.HTTPFlow,
    monkeypatch: pytest.MonkeyPatch,
    *,
    queue: asyncio.Queue[str] | None = None,
) -> tuple[RequestFlowState, str, dict[str, Any] | None]:
    _patch_pipeline(monkeypatch)
    await addon_handlers.handle_http_request(flow, None)
    state = get_request_flow_state(flow)
    assert state is not None
    exchange_id = state.provisional_exchange_id
    assert exchange_id is not None
    event = _event(queue) if queue is not None else None
    return state, exchange_id, event


async def test_http_request_hook_emits_pending_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-emit")
    _patch_pipeline(monkeypatch)
    queue = broadcast.subscribe()

    await addon_handlers.handle_http_request(flow, None)

    state = get_request_flow_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is not None
    entry = await _single_entry()
    assert entry.id == state.provisional_exchange_id
    assert entry.res is None
    assert entry.pipeline is not None
    assert entry.pipeline.chars_before == 100
    assert entry.pipeline.chars_after == 80
    assert entry.pipeline.tokens_before is None
    assert entry.pipeline.tokens_after is None

    event = _event(queue)
    assert event["type"] == "exchange"
    assert event["id"] == entry.id
    assert event["flow_id"] == flow.id
    assert event["res"] is None
    assert event["pipeline"] == entry.pipeline.model_dump(mode="json")


async def test_http_request_hook_emits_before_breakpoint_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-breakpoint")
    _patch_pipeline(monkeypatch)
    bp.arm()

    task = asyncio.create_task(addon_handlers.handle_http_request(flow, None))
    await _wait_for_pause(flow.id)

    state = get_request_flow_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is not None
    storage = await get_storage()
    entry = await storage.read_index_entry(state.provisional_exchange_id)
    assert entry is not None
    assert entry.res is None

    await bp.release(flow.id)
    await task


async def test_http_request_hook_emits_when_breakpoint_skip_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-skip")
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(addon_handlers, "_should_skip_breakpoint", lambda model: True)
    bp.arm()

    await addon_handlers.handle_http_request(flow, None)

    state = get_request_flow_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is not None
    entry = await _single_entry()
    assert entry.id == state.provisional_exchange_id
    assert entry.res is None


async def test_http_response_hook_finalizes_same_exchange_and_observes_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-finalize")
    calls: list[tuple[str | None, RequestFlowState, InternalResponse | None, str | None]] = []

    def fake_track_assignment(
        run_id: str | None,
        request_state: RequestFlowState,
        res_ir: InternalResponse | None,
        *,
        exchange_id: str | None = None,
    ) -> TrackAssignment | None:
        calls.append((run_id, request_state, res_ir, exchange_id))
        return None

    monkeypatch.setattr(
        "transport_matters.exchange_recorder.persist_track_assignment",
        fake_track_assignment,
    )
    state, exchange_id, _ = await _request_pending(flow, monkeypatch)
    _set_response(flow, _response_body(text="final text"))
    counter = _SeqCounter([321, 123])

    await addon_handlers.handle_response(flow, counter)

    storage = await get_storage()
    entry = await storage.read_index_entry(exchange_id)
    assert entry is not None
    assert entry.res is not None
    assert entry.res.stop_reason == "end_turn"
    assert entry.res.text_chars == len("final text")
    assert entry.pipeline is not None
    assert entry.pipeline.tokens_before == 321
    assert entry.pipeline.tokens_after == 123
    assert counter.auth_headers == [{"x-api-key": "test-key"}] * 2
    assert calls[0][0] == "run-http"
    assert calls[0][1].curated_request_ir == state.curated_request_ir
    assert calls[0][2] is None
    assert calls[0][3] == exchange_id
    assert calls[1][0] == "run-http"
    assert calls[1][1].curated_request_ir == state.curated_request_ir
    assert calls[1][1].provisional_exchange_id == exchange_id
    assert calls[1][2] is not None
    assert calls[1][2].stop_reason == "end_turn"
    assert calls[1][3] == exchange_id


async def test_http_response_hook_keeps_req_stats_json_equivalent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-req-stats")
    queue = broadcast.subscribe()
    _state, exchange_id, pending = await _request_pending(flow, monkeypatch, queue=queue)
    assert pending is not None
    _set_response(flow, _response_body())

    await addon_handlers.handle_response(flow, None)

    final = _event(queue)
    assert final["id"] == exchange_id
    assert final["req"] == pending["req"]


async def test_http_breakpoint_edit_updates_final_req_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-edit")
    _patch_pipeline(monkeypatch, message_text="short")
    queue = broadcast.subscribe()
    bp.arm()

    task = asyncio.create_task(addon_handlers.handle_http_request(flow, None))
    pending = await _wait_event(queue)
    assert pending["type"] == "exchange"
    await _wait_for_pause(flow.id)

    paused = await bp.get_paused()
    edited_ir = _curated_ir(paused[flow.id].curated_ir, message_text="much longer")
    await bp.release(flow.id, edited_ir)
    await task
    _set_response(flow, _response_body())

    await addon_handlers.handle_response(flow, None)

    final = await _wait_event(queue)
    if final["type"] == "paused":
        final = await _wait_event(queue)
    assert final["type"] == "exchange"
    assert final["id"] == pending["id"]
    assert final["req"] != pending["req"]
    assert final["req"]["messages_chars"] > pending["req"]["messages_chars"]

    storage = await get_storage()
    artifacts = await storage.read_exchange(cast("str", final["id"]))
    assert artifacts.request_curated_ir is not None
    block = artifacts.request_curated_ir.messages[0].content[0]
    assert isinstance(block, TextBlock)
    assert block.text == "much longer"


async def test_http_breakpoint_drop_deletes_provisional_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-drop")
    _patch_pipeline(monkeypatch)
    queue = broadcast.subscribe()
    bp.arm()

    task = asyncio.create_task(addon_handlers.handle_http_request(flow, None))
    pending = await _wait_event(queue)
    await _wait_for_pause(flow.id)
    await bp.drop(flow.id)
    await task

    state = get_request_flow_state(flow)
    assert state is not None
    assert state.dropped is True
    await addon_handlers.handle_response(flow, None)

    storage = await get_storage()
    assert await storage.read_index_entry(cast("str", pending["id"])) is None
    deleted = await _wait_event(queue)
    if deleted["type"] == "paused":
        deleted = await _wait_event(queue)
    assert deleted == {
        "type": "exchange_deleted",
        "id": pending["id"],
        "flow_id": flow.id,
    }


async def test_http_error_hook_deletes_provisional_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-error")
    queue = broadcast.subscribe()
    _state, exchange_id, _ = await _request_pending(flow, monkeypatch, queue=queue)

    await TransportMattersAddon().error(flow)

    storage = await get_storage()
    assert await storage.read_index_entry(exchange_id) is None
    deleted = _event(queue)
    assert deleted == {
        "type": "exchange_deleted",
        "id": exchange_id,
        "flow_id": flow.id,
    }


@pytest.mark.parametrize("status_code", [400, 500])
async def test_http_error_response_finalizes_instead_of_deleting(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    flow = _http_flow(f"flow-http-{status_code}")
    queue = broadcast.subscribe()
    _state, exchange_id, pending = await _request_pending(flow, monkeypatch, queue=queue)
    assert pending is not None
    _set_response(
        flow,
        {"type": "error", "error": {"type": "api_error", "message": "boom"}},
        status_code=status_code,
    )

    await addon_handlers.handle_response(flow, None)

    storage = await get_storage()
    entry = await storage.read_index_entry(exchange_id)
    assert entry is not None
    assert entry.res is not None
    assert entry.res.stop_reason == f"http_{status_code}"
    assert _event(queue)["id"] == exchange_id


async def test_http_response_hook_falls_back_when_provisional_emit_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-emit-failed")
    _patch_pipeline(monkeypatch)

    async def fake_persist(
        persist_flow: http.HTTPFlow,
        request_state: RequestFlowState,
    ) -> None:
        assert persist_flow is flow
        assert request_state.provisional_exchange_id is None

    monkeypatch.setattr(
        addon_handlers,
        "persist_http_provisional_exchange",
        fake_persist,
    )

    await addon_handlers.handle_http_request(flow, None)
    _set_response(flow, _response_body())
    await addon_handlers.handle_response(flow, None)

    entry = await _single_entry()
    assert entry.res is not None
    assert entry.id != ""


async def test_http_response_hook_falls_back_when_provisional_record_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-missing")
    _state, exchange_id, _ = await _request_pending(flow, monkeypatch)
    storage = await get_storage()
    await storage.delete_exchange(exchange_id)
    _set_response(flow, _response_body())

    await addon_handlers.handle_response(flow, None)

    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    assert entries[0].id != exchange_id
    assert entries[0].res is not None


async def test_http_create_fresh_synthesizes_error_stats_when_provisional_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-create-fresh-error")
    _patch_pipeline(monkeypatch)

    async def fake_persist(
        persist_flow: http.HTTPFlow,
        request_state: RequestFlowState,
    ) -> None:
        assert persist_flow is flow
        assert request_state.provisional_exchange_id is None

    monkeypatch.setattr(
        addon_handlers,
        "persist_http_provisional_exchange",
        fake_persist,
    )

    await addon_handlers.handle_http_request(flow, None)
    _set_response(
        flow,
        {"type": "error", "error": {"type": "api_error", "message": "boom"}},
        status_code=500,
    )

    await addon_handlers.handle_response(flow, None)

    entry = await _single_entry()
    assert entry.res is not None
    assert entry.res.stop_reason == "http_500"
    assert entry.res.text_chars > 0


async def test_http_drop_wins_over_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _http_flow("flow-http-drop-wins")
    queue = broadcast.subscribe()
    _state, exchange_id, _ = await _request_pending(flow, monkeypatch, queue=queue)
    state = update_request_flow_state(flow, dropped=True)
    assert state is not None
    _set_response(flow, _response_body())

    async def fail_finalize(
        finalize_flow: http.HTTPFlow,
        finalize_state: RequestFlowState,
        token_counter: TokenCountingClient | None,
    ) -> bool:
        raise AssertionError("dropped HTTP flow must not finalize")

    monkeypatch.setattr(
        "transport_matters.exchange_recorder._finalize_http_provisional_exchange",
        fail_finalize,
    )

    await addon_handlers.handle_response(flow, None)

    storage = await get_storage()
    updated_state = get_request_flow_state(flow)
    assert updated_state is not None
    assert updated_state.dropped is True
    assert await storage.read_index_entry(exchange_id) is None
    deleted = _event(queue)
    assert deleted["type"] == "exchange_deleted"
    assert deleted["id"] == exchange_id


async def test_http_concurrent_flows_isolate_provisional_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _http_flow("flow-http-concurrent-a", message_text="first")
    second = _http_flow("flow-http-concurrent-b", message_text="second")
    _first_state, first_id, _ = await _request_pending(first, monkeypatch)
    _second_state, second_id, _ = await _request_pending(second, monkeypatch)
    assert first_id != second_id

    update_request_flow_state(first, dropped=True)
    _set_response(first, _response_body(text="unused"))
    _set_response(second, _response_body(text="second response"))

    await addon_handlers.handle_response(first, None)
    await addon_handlers.handle_response(second, None)

    storage = await get_storage()
    assert await storage.read_index_entry(first_id) is None
    second_entry = await storage.read_index_entry(second_id)
    assert second_entry is not None
    assert second_entry.res is not None
    assert second_entry.res.text_chars == len("second response")
    first_state = get_request_flow_state(first)
    second_state = get_request_flow_state(second)
    assert first_state is not None
    assert second_state is not None
    assert first_state.provisional_exchange_id is None
    assert second_state.provisional_exchange_id == second_id
