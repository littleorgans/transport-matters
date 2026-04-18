"""Tests for Codex websocket transport capture."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from mitmproxy import http, websocket
from mitmproxy.test import tflow
from wsproto.frame_protocol import Opcode

from manicure import breakpoint as bp
from manicure import broadcast
from manicure.addon import ManicureAddon
from manicure.codex.diagnostics import build_codex_transport_diagnostics
from manicure.codex.response_parser import parse_codex_response_payloads
from manicure.codex.transport import (
    build_codex_transport_artifacts,
    close_codex_transport,
    ensure_codex_transport_state,
    is_codex_websocket_flow,
    record_codex_websocket_message,
)
from manicure.overrides import Override, get_store
from manicure.storage import get_storage, init_storage, reset_storage

if TYPE_CHECKING:
    from collections.abc import Generator


def _codex_flow() -> http.HTTPFlow:
    flow = tflow.twebsocketflow(messages=False)
    assert flow.response is not None
    assert flow.websocket is not None
    flow.request.host = "chatgpt.com"
    flow.request.path = "/backend-api/codex/responses?client=cli"
    flow.request.headers["x-codex-session"] = "sess-123"
    flow.response.headers["x-upstream"] = "chatgpt"
    flow.id = "flow-codex-1"
    return flow


def _codex_handshake_failure_flow(
    status_code: int = 403,
    body: bytes = b'{"detail":"Unauthorized websocket upgrade"}',
) -> http.HTTPFlow:
    flow = tflow.tflow()
    flow.request.host = "chatgpt.com"
    flow.request.scheme = "https"
    flow.request.path = "/backend-api/codex/responses?client=cli"
    flow.request.headers["origin"] = "https://chatgpt.com"
    flow.response = http.Response.make(
        status_code,
        body,
        {"content-type": "application/json"},
    )
    flow.id = "flow-codex-handshake"
    return flow


async def _wait_for_pause(flow_id: str) -> None:
    for _ in range(200):
        paused = await bp.get_paused()
        if flow_id in paused:
            return
        await asyncio.sleep(0.001)
    raise AssertionError("flow never paused")


def test_is_codex_websocket_flow_only_matches_target_path() -> None:
    flow = _codex_flow()
    assert is_codex_websocket_flow(flow) is True

    flow.request.path = "/backend-api/plugins/featured"
    assert is_codex_websocket_flow(flow) is False

    flow.request.host = "chatgpt.com"
    flow.request.path = "/backend-api/codex/responses-extra"
    assert is_codex_websocket_flow(flow) is False

    flow.request.host = "api.openai.com"
    flow.request.path = "/backend-api/codex/responses"
    assert is_codex_websocket_flow(flow) is False


def test_ensure_codex_transport_state_captures_upgrade_metadata() -> None:
    flow = _codex_flow()

    state = ensure_codex_transport_state(flow)

    assert state is not None
    assert state.upgrade.host == "chatgpt.com"
    assert state.upgrade.path == "/backend-api/codex/responses?client=cli"
    assert state.upgrade.response_status_code == 101
    assert ("x-codex-session", "sess-123") in state.upgrade.request_headers
    assert ("x-upstream", "chatgpt") in state.upgrade.response_headers


def test_record_codex_websocket_message_tracks_counts_and_initial_frame() -> None:
    flow = _codex_flow()
    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert flow.websocket is not None

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT, False, b'{"type":"response.output_text.delta"}'
        )
    )
    update = record_codex_websocket_message(flow)
    assert update is not None
    state, _, captured_initial = update
    assert captured_initial is False
    assert state.server_message_count == 1
    assert state.initial_client_frame is None

    first_client_frame = b'{"type":"response.create","instructions":"hi"}'
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, first_client_frame)
    )
    update = record_codex_websocket_message(flow)
    assert update is not None
    state, _, captured_initial = update
    assert captured_initial is True
    assert state.client_message_count == 1
    assert state.initial_client_frame == first_client_frame
    assert state.initial_client_frame_text == first_client_frame.decode()
    assert state.initial_client_frame_is_text is True

    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.cancel"}')
    )
    update = record_codex_websocket_message(flow)
    assert update is not None
    state, _, captured_initial = update
    assert captured_initial is False
    assert state.client_message_count == 2
    assert state.initial_client_frame == first_client_frame

    second_client_frame = b'{"type":"response.create","instructions":"second"}'
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, second_client_frame)
    )
    update = record_codex_websocket_message(flow)
    assert update is not None
    state, _, captured_initial = update
    assert captured_initial is True
    assert state.client_message_count == 3
    assert state.initial_client_frame == second_client_frame
    assert state.initial_client_frame_text == second_client_frame.decode()


def test_close_codex_transport_reports_close_state() -> None:
    flow = _codex_flow()
    ensure_codex_transport_state(flow)
    assert flow.websocket is not None
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.create"}')
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1011
    flow.websocket.close_reason = "upstream reset"
    flow.websocket.closed_by_client = False

    summary = close_codex_transport(flow)

    assert summary is not None
    assert summary.close_code == 1011
    assert summary.close_reason == "upstream reset"
    assert summary.closed_by_client is False
    assert summary.initial_client_frame_captured is True
    assert summary.is_normal is False


def test_build_codex_transport_artifacts_redacts_sensitive_upgrade_headers() -> None:
    flow = _codex_flow()
    flow.request.headers["authorization"] = "Bearer super-secret"
    flow.request.headers["cookie"] = "oai-session=secret"
    assert flow.response is not None
    flow.response.headers["set-cookie"] = "session=secret; Path=/"

    ensure_codex_transport_state(flow)
    transport = build_codex_transport_artifacts(flow)

    assert transport is not None
    request_headers = {
        header.name: header.value for header in transport.upgrade.request_headers
    }
    response_headers = {
        header.name: header.value for header in transport.upgrade.response_headers
    }
    assert request_headers["authorization"] == "Bearer [redacted]"
    assert request_headers["cookie"] == "[redacted]"
    assert request_headers["x-codex-session"] == "[redacted]"
    assert response_headers["set-cookie"] == "[redacted]"
    assert response_headers["x-upstream"] == "chatgpt"


def test_parse_codex_response_payloads_prefers_completed_output_items_and_usage() -> (
    None
):
    response = parse_codex_response_payloads(
        [
            {
                "type": "response.output_item.done",
                "item": {
                    "id": "rs_01",
                    "type": "reasoning",
                    "status": "completed",
                    "encrypted_content": "opaque",
                    "summary": [
                        {"type": "summary_text", "text": "considering tradeoffs"}
                    ],
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "id": "fc_01",
                    "call_id": "call_01",
                    "type": "function_call",
                    "status": "completed",
                    "name": "exec_command",
                    "arguments": '{"cmd":"pwd"}',
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "id": "msg_01",
                    "type": "message",
                    "status": "completed",
                    "phase": "final_answer",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "assistant text"},
                    ],
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_01",
                    "model": "gpt-5-codex",
                    "status": "completed",
                    "usage": {
                        "input_tokens": 12,
                        "input_tokens_details": {"cached_tokens": 5},
                        "output_tokens": 7,
                    },
                },
            },
        ]
    )

    assert response is not None
    assert response.id == "resp_01"
    assert response.model == "codex/gpt-5-codex"
    assert response.stop_reason == "completed"
    assert response.usage.input_tokens == 12
    assert response.usage.cache_read_input_tokens == 5
    assert response.usage.output_tokens == 7
    assert response.content[0].type == "thinking"
    assert response.content[1].type == "tool_use"
    assert response.content[2].type == "text"
    assert response.content[2].text == "assistant text"
    assert response.provider_extras["output_item_meta"][2]["phase"] == "final_answer"


@pytest.fixture(autouse=True)
def _reset_breakpoint_and_overrides() -> None:
    bp.disarm()
    bp._paused.clear()
    store = get_store()
    store.clear()
    store.enabled = True


@pytest.fixture(autouse=True)
def _reset_storage(tmp_path: Any) -> Generator[None]:
    reset_storage()
    init_storage(root=tmp_path)
    yield
    reset_storage()


async def test_addon_websocket_message_applies_pipeline_to_initial_frame() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None
    store = get_store()
    store.upsert(Override(kind="system_part_text", target="system:0", value="patched"))

    addon.websocket_start(flow)
    original = (
        b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}'
    )
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, original)
    )

    await addon.websocket_message(flow)

    payload = json.loads(flow.websocket.messages[-1].content.decode())
    assert payload["instructions"] == "patched"
    assert flow.websocket.messages[-1].dropped is False
    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert state.initial_client_frame == original
    ir = flow.metadata.get("manicure_ir")
    assert ir is not None
    assert ir.provider == "codex"
    assert ir.model == "codex/gpt-5-codex"


async def test_addon_websocket_message_pauses_and_rewrites_on_release() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None
    bp.arm()

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )

    task = asyncio.create_task(addon.websocket_message(flow))
    await _wait_for_pause(flow.id)

    paused = await bp.get_paused()
    pf = paused[flow.id]
    edited_ir = pf.curated_ir.model_copy(
        update={
            "system": [
                part.model_copy(update={"text": "edited"})
                for part in pf.curated_ir.system
            ]
        }
    )
    await bp.release(
        flow.id,
        edited_ir,
        b'{"type":"response.create","model":"gpt-5-codex","instructions":"edited","input":[],"tools":[]}',
    )
    await task

    assert flow.websocket.messages[-1].dropped is False
    payload = json.loads(flow.websocket.messages[-1].content.decode())
    assert payload["instructions"] == "edited"
    assert flow.metadata["manicure_curated_ir"].system[0].text == "edited"
    assert await bp.get_paused() == {}


async def test_addon_websocket_message_persists_provisional_codex_exchange() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )

    await addon.websocket_message(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.provider == "codex"
    assert entry.res is None

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.request_ir.provider == "codex"
    assert artifacts.transport is not None
    assert artifacts.transport.close is None
    assert artifacts.transport.messages[-1].event_type == "response.create"


async def test_addon_websocket_message_keeps_provisional_exchange_visible_while_paused() -> (
    None
):
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None
    bp.arm()

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )

    task = asyncio.create_task(addon.websocket_message(flow))
    await _wait_for_pause(flow.id)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    assert entries[0].provider == "codex"
    assert entries[0].res is None

    await bp.drop(flow.id)
    await task

    assert await storage.read_index(limit=10, offset=0) == []


async def test_addon_websocket_message_drops_initial_frame_when_user_drops() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None
    bp.arm()

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )

    task = asyncio.create_task(addon.websocket_message(flow))
    await _wait_for_pause(flow.id)

    await bp.drop(flow.id)
    await task

    assert flow.websocket.messages[-1].dropped is True
    storage = await get_storage()
    assert await storage.read_index(limit=10, offset=0) == []
    assert await bp.get_paused() == {}


async def test_addon_websocket_message_still_drops_when_cleanup_fails() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None
    bp.arm()

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )

    storage = await get_storage()
    task = asyncio.create_task(addon.websocket_message(flow))
    await _wait_for_pause(flow.id)

    with patch.object(
        storage,
        "delete_exchange",
        new=AsyncMock(side_effect=OSError("disk full")),
    ):
        await bp.drop(flow.id)
        await task

    assert flow.websocket.messages[-1].dropped is True
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    assert await bp.get_paused() == {}


async def test_addon_websocket_end_skips_persisting_dropped_codex_exchange() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None
    bp.arm()

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )

    task = asyncio.create_task(addon.websocket_message(flow))
    await _wait_for_pause(flow.id)

    await bp.drop(flow.id)
    await task

    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "dropped"
    flow.websocket.closed_by_client = True
    queue = broadcast.subscribe()
    try:
        await addon.websocket_end(flow)
        storage = await get_storage()
        assert await storage.read_index(limit=10, offset=0) == []
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.01)
    finally:
        broadcast.unsubscribe(queue)


async def test_addon_websocket_end_logs_abnormal_server_close(caplog: Any) -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.create"}')
    )
    await addon.websocket_message(flow)
    flow.websocket.close_code = 1011
    flow.websocket.close_reason = "upstream failure"
    flow.websocket.closed_by_client = False

    with caplog.at_level(logging.WARNING, logger="manicure.addon"):
        await addon.websocket_end(flow)

    assert "CODEX WS END flow-codex-1 close_code=1011 closer=server" in caplog.text


async def test_addon_websocket_end_persists_codex_exchange() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )
    await addon.websocket_message(flow)
    storage = await get_storage()
    provisional = await storage.read_index(limit=10, offset=0)
    assert len(provisional) == 1
    assert provisional[0].res is None
    provisional_id = provisional[0].id
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.output_text.delta","delta":"hello"}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "done"
    flow.websocket.closed_by_client = False

    queue = broadcast.subscribe()
    try:
        await addon.websocket_end(flow)
        event = json.loads(await asyncio.wait_for(queue.get(), timeout=0.01))
        assert event["type"] == "exchange"
        assert event["id"] == provisional_id
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.01)
    finally:
        broadcast.unsubscribe(queue)

    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == provisional_id
    assert entry.provider == "codex"
    assert entry.res is not None
    assert entry.res.stop_reason == "completed"
    assert entry.res.text_chars == 5

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.request_ir.provider == "codex"
    assert artifacts.request_audit is not None
    assert artifacts.transport is not None
    assert artifacts.transport.upgrade.host == "chatgpt.com"
    assert artifacts.transport.close is not None
    assert artifacts.transport.close.close_code == 1000
    assert len(artifacts.transport.messages) >= 3
    assert artifacts.transport.messages[-3].event_type == "response.create"
    assert artifacts.transport.messages[-2].event_type == "response.output_text.delta"
    assert artifacts.transport.messages[-1].event_type == "response.completed"


async def test_addon_websocket_end_survives_default_executor_shutdown() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )
    await addon.websocket_message(flow)
    storage = await get_storage()
    provisional = await storage.read_index(limit=10, offset=0)
    assert len(provisional) == 1
    provisional_id = provisional[0].id

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.output_text.delta","delta":"hello"}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1006
    flow.websocket.close_reason = ""
    flow.websocket.closed_by_client = True

    loop = asyncio.get_running_loop()
    original_run_in_executor = loop.run_in_executor

    async def fail_default_executor(
        executor: object,
        func: object,
        *args: object,
    ) -> object:
        if executor is None:
            raise RuntimeError("Executor shutdown has been called")
        return await original_run_in_executor(
            cast("Any", executor),
            cast("Any", func),
            *args,
        )

    with patch.object(loop, "run_in_executor", side_effect=fail_default_executor):
        await addon.websocket_end(flow)

    entry = await storage.read_index_entry(provisional_id)
    assert entry is not None
    assert entry.res is not None
    assert entry.res.stop_reason == "completed"

    artifacts = await storage.read_exchange(provisional_id)
    assert artifacts.transport is not None
    assert artifacts.transport.close is not None
    assert artifacts.transport.close.close_code == 1006
    assert artifacts.transport.close.closed_by_client is True
    assert artifacts.transport.messages[-2].event_type == "response.output_text.delta"
    assert artifacts.transport.messages[-1].event_type == "response.completed"


async def test_addon_websocket_end_cancellation_restores_provisional_exchange() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )
    await addon.websocket_message(flow)
    storage = await get_storage()
    provisional = await storage.read_index(limit=10, offset=0)
    assert len(provisional) == 1
    provisional_id = provisional[0].id

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "done"
    flow.websocket.closed_by_client = False

    async def cancel_rewrite(_: dict[str, object]) -> None:
        raise asyncio.CancelledError()

    with (
        patch.object(storage, "_rewrite_index", side_effect=cancel_rewrite),
        pytest.raises(asyncio.CancelledError),
    ):
        await addon.websocket_end(flow)

    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    assert entries[0].id == provisional_id
    assert entries[0].res is None

    artifacts = await storage.read_exchange(provisional_id)
    assert artifacts.transport is not None
    assert artifacts.transport.close is None
    assert artifacts.transport.messages[-1].event_type == "response.create"


async def test_addon_websocket_end_tolerates_nested_non_string_type_fields() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            (
                b'{"type":"response.output_item.added","item":{"type":{"kind":"tool"},"id":"item-1"}}'
            ),
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "done"
    flow.websocket.closed_by_client = False

    await addon.websocket_end(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.provider == "codex"
    assert entry.res is not None
    assert entry.res.stop_reason == "completed"
    assert entry.res.tool_calls == 0


async def test_addon_response_persists_codex_handshake_failure() -> None:
    addon = ManicureAddon()
    flow = _codex_handshake_failure_flow()

    await addon.response(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.provider == "codex"
    assert entry.model == "codex/transport-handshake"
    assert entry.res is not None
    assert entry.res.stop_reason == "websocket_handshake_failed"

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.response_raw is not None
    assert b"Unauthorized websocket upgrade" in artifacts.response_raw
    assert artifacts.transport is not None
    assert artifacts.transport.upgrade.response_status_code == 403
    assert artifacts.transport.messages == []


async def test_addon_response_preserves_raw_handshake_failure_bytes() -> None:
    addon = ManicureAddon()
    raw_body = (
        b"TLS error: invalid peer certificate: UnknownIssuer\xff"
        b"\xfe while upgrading websocket"
    )
    flow = _codex_handshake_failure_flow(status_code=502, body=raw_body)

    await addon.response(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1

    artifacts = await storage.read_exchange(entries[0].id)
    assert artifacts.response_raw == raw_body
    diagnostics = build_codex_transport_diagnostics(artifacts)
    assert diagnostics[0].code == "proxy_trust_failed"
    assert "response body redacted" in (diagnostics[0].detail or "")
    assert "UnknownIssuer" not in (diagnostics[0].detail or "")
