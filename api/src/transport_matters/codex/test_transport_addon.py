"""Addon websocket-message coverage for Codex transport capture."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from transport_matters import breakpoint as bp
from transport_matters import broadcast
from transport_matters.addon import TransportMattersAddon
from transport_matters.codex.test_transport_support import _codex_flow, _wait_for_pause
from transport_matters.override_state import root_scope
from transport_matters.overrides import Override, get_store
from transport_matters.storage import get_storage

pytest_plugins = ("transport_matters.codex.test_transport_support",)
pytestmark = pytest.mark.usefixtures("codex_run_id")


async def test_addon_websocket_message_applies_pipeline_to_initial_frame() -> None:
    addon = TransportMattersAddon()
    flow = _codex_flow()
    assert flow.websocket is not None
    store = get_store()
    store.upsert(
        Override(kind="system_part_text", target="system:0", value="patched"),
        scope=root_scope("run-codex"),
    )

    addon.websocket_start(flow)
    original = b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}'
    flow.websocket.messages.append(websocket.WebSocketMessage(Opcode.TEXT, True, original))

    await addon.websocket_message(flow)

    payload = json.loads(flow.websocket.messages[-1].content.decode())
    assert payload["instructions"] == "patched"
    assert flow.websocket.messages[-1].dropped is False
    ir = flow.metadata.get("transport_matters_ir")
    assert ir is not None
    assert ir.provider == "codex"
    assert ir.model == "codex/gpt-5-codex"


async def test_addon_websocket_message_pauses_and_rewrites_on_release() -> None:
    addon = TransportMattersAddon()
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
    queue = broadcast.subscribe("run-codex")

    try:
        paused = await bp.get_paused()
        pf = paused[flow.id]
        edited_ir = pf.curated_ir.model_copy(
            update={
                "system": [
                    part.model_copy(update={"text": "edited"}) for part in pf.curated_ir.system
                ]
            }
        )
        await bp.release(
            flow.id,
            edited_ir,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"edited","input":[],"tools":[]}',
        )
        await task

        event = json.loads(await asyncio.wait_for(queue.get(), timeout=0.01))
        assert event["type"] == "exchange"
        assert event["flow_id"] == flow.id
        assert event["mutated_manually"] is True
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.01)
    finally:
        broadcast.unsubscribe(queue)

    assert flow.websocket.messages[-1].dropped is False
    payload = json.loads(flow.websocket.messages[-1].content.decode())
    assert payload["instructions"] == "edited"
    assert flow.metadata["transport_matters_curated_ir"].system[0].text == "edited"
    assert await bp.get_paused() == {}

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    assert entries[0].mutated_manually is True
    artifacts = await storage.read_exchange(entries[0].id)
    assert artifacts.request_curated_raw is not None
    assert b'"instructions":"edited"' in artifacts.request_curated_raw
    assert artifacts.turn is not None
    assert artifacts.turn.status == "open"
    assert artifacts.events is not None
    assert tuple(event.kind for event in artifacts.events) == (
        "turn_started",
        "request_curated",
        "breakpoint_paused",
        "breakpoint_released",
    )


async def test_addon_websocket_message_persists_provisional_codex_exchange() -> None:
    addon = TransportMattersAddon()
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
    assert artifacts.events is not None
    assert tuple(event.kind for event in artifacts.events) == ("turn_started",)
    assert artifacts.turn is not None
    assert artifacts.turn.turn_index == 0
    assert artifacts.turn.request_message_index == 0
    assert artifacts.turn.status == "open"
    assert artifacts.turn.cursor is not None
    assert artifacts.turn.cursor.next_message_index == 1
    assert artifacts.turn.started_at == artifacts.transport.messages[0].ts


async def test_addon_websocket_message_derives_session_from_current_codex_headers() -> None:
    addon = TransportMattersAddon()
    flow = _codex_flow()
    assert flow.websocket is not None
    flow.request.headers["session-id"] = "sess-real"
    flow.request.headers["thread-id"] = "thread-real"
    flow.request.headers["x-codex-turn-metadata"] = json.dumps(
        {"session_id": "sess-real", "thread_id": "thread-real", "turn_id": "turn-real"}
    )

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            json.dumps(
                {
                    "type": "response.create",
                    "model": "gpt-5-codex",
                    "client_metadata": {
                        "x-codex-turn-metadata": json.dumps(
                            {"session_id": "sess-real", "turn_id": "turn-real"}
                        )
                    },
                }
            ).encode(),
        )
    )

    await addon.websocket_message(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1

    artifacts = await storage.read_exchange(entries[0].id)
    # The parser now resolves the codex id from the nested x-codex-turn-metadata into
    # metadata.session_id (§7.2 read-back correlation) — previously this was None.
    assert artifacts.request_ir.metadata.session_id == "sess-real"
    assert artifacts.events is not None
    assert artifacts.turn is not None
    assert artifacts.turn.session_id == "sess-real"
    assert artifacts.turn.turn_id == "turn-real"
    assert artifacts.turn.turn_index == 0
    assert tuple(event.kind for event in artifacts.events) == ("turn_started",)


async def test_addon_websocket_message_advances_provisional_codex_exchange_on_server_frames() -> (
    None
):
    addon = TransportMattersAddon()
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

    queue = broadcast.subscribe("run-codex")
    try:
        flow.websocket.messages.append(
            websocket.WebSocketMessage(
                Opcode.TEXT,
                False,
                b'{"type":"response.output_text.delta","delta":"hello"}',
            )
        )
        await addon.websocket_message(flow)

        event = json.loads(await asyncio.wait_for(queue.get(), timeout=0.01))
        assert event["id"] == provisional_id
        assert event["res"] is None
        assert event["codex_turn"] == {
            "turn_index": 0,
            "message_range_start": 0,
            "message_range_end": 1,
            "status": "open",
            "terminal_cause": None,
            "stop_reason": None,
            "text_chars": len("hello"),
            "tool_calls": 0,
        }
    finally:
        broadcast.unsubscribe(queue)

    entry = await storage.read_index_entry(provisional_id)
    assert entry is not None
    assert entry.codex_turn is not None
    assert entry.codex_turn.message_range_end == 1
    assert entry.codex_turn.text_chars == len("hello")

    artifacts = await storage.read_exchange(provisional_id)
    assert artifacts.transport is not None
    assert [message.event_type for message in artifacts.transport.messages] == [
        "response.create",
        "response.output_text.delta",
    ]
    assert artifacts.events is not None
    assert tuple(event.kind for event in artifacts.events) == ("turn_started",)
    assert artifacts.turn is not None
    assert artifacts.turn.message_range_end == 1
    assert artifacts.turn.text_chars == len("hello")
    assert artifacts.turn.cursor is not None
    assert artifacts.turn.cursor.next_message_index == 2


async def test_addon_websocket_message_projects_open_tool_activity_into_list_summary() -> None:
    addon = TransportMattersAddon()
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

    queue = broadcast.subscribe("run-codex")
    try:
        flow.websocket.messages.append(
            websocket.WebSocketMessage(
                Opcode.TEXT,
                False,
                (
                    b'{"type":"response.output_item.added","item":{"type":"function_call","id":"fc_01","call_id":"call_read","name":"read_file","arguments":""}}'
                ),
            )
        )
        await addon.websocket_message(flow)

        live_event = json.loads(await asyncio.wait_for(queue.get(), timeout=0.01))
        assert live_event["id"] == provisional_id
        assert live_event["res"] is None
        assert live_event["codex_turn"]["status"] == "open"
        assert live_event["codex_turn"]["tool_calls"] == 1

        open_entry = await storage.read_index_entry(provisional_id)
        assert open_entry is not None
        assert open_entry.codex_turn is not None
        assert open_entry.codex_turn.tool_calls == 1

        open_artifacts = await storage.read_exchange(provisional_id)
        assert open_artifacts.turn is not None
        assert open_artifacts.turn.tool_calls == 0
        assert open_artifacts.turn.cursor is not None
        assert len(open_artifacts.turn.cursor.open_tool_calls) == 1

        flow.websocket.messages.append(
            websocket.WebSocketMessage(
                Opcode.TEXT,
                False,
                b'{"type":"response.failed","response":{"status":"failed"}}',
            )
        )
        await addon.websocket_message(flow)

        final_event = json.loads(await asyncio.wait_for(queue.get(), timeout=0.01))
        assert final_event["id"] == provisional_id
        assert final_event["res"]["stop_reason"] == "failed"
        assert final_event["res"]["tool_calls"] == 0
        assert final_event["codex_turn"]["status"] == "failed"
        assert final_event["codex_turn"]["tool_calls"] == 1
    finally:
        broadcast.unsubscribe(queue)

    finalized_entry = await storage.read_index_entry(provisional_id)
    assert finalized_entry is not None
    assert finalized_entry.res is not None
    assert finalized_entry.res.stop_reason == "failed"
    assert finalized_entry.res.tool_calls == 0
    assert finalized_entry.codex_turn is not None
    assert finalized_entry.codex_turn.status == "failed"
    assert finalized_entry.codex_turn.tool_calls == 1


async def test_addon_websocket_message_keeps_provisional_exchange_visible_while_paused() -> None:
    addon = TransportMattersAddon()
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
    addon = TransportMattersAddon()
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
    addon = TransportMattersAddon()
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
