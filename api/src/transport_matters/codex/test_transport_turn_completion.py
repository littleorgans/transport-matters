"""Codex websocket turn completion and finalization coverage."""

from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from transport_matters.addon import TransportMattersAddon
from transport_matters.codex.test_transport_support import _codex_flow
from transport_matters.codex.transport import ensure_codex_transport_state
from transport_matters.storage import get_storage

pytest_plugins = ("transport_matters.codex.test_transport_support",)


async def test_addon_websocket_message_finalizes_turn_on_server_completion() -> None:
    addon = TransportMattersAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"first"}',
        )
    )
    await addon.websocket_message(flow)

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.output_text.delta","delta":"hello"}',
        )
    )
    await addon.websocket_message(flow)

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    await addon.websocket_message(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1

    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is None

    finalized_entry = entries[0]
    assert finalized_entry.res is not None
    assert finalized_entry.res.stop_reason == "completed"
    assert finalized_entry.res.text_chars == 5
    assert finalized_entry.codex_turn is not None
    assert finalized_entry.codex_turn.status == "completed"
    assert finalized_entry.codex_turn.message_range_start == 0
    assert finalized_entry.codex_turn.message_range_end == 2

    finalized_artifacts = await storage.read_exchange(finalized_entry.id)
    assert finalized_artifacts.response_ir is not None
    assert finalized_artifacts.response_ir.provider == "codex"
    assert finalized_artifacts.response_ir.stop_reason == "completed"
    assert finalized_artifacts.response_ir.content[0].type == "text"
    assert finalized_artifacts.response_ir.content[0].text == "hello"
    assert finalized_artifacts.transport is not None
    assert [m.event_type for m in finalized_artifacts.transport.messages] == [
        "response.create",
        "response.output_text.delta",
        "response.completed",
    ]
    assert finalized_artifacts.transport.close is None
    assert finalized_artifacts.events is not None
    assert tuple(event.kind for event in finalized_artifacts.events) == (
        "turn_started",
        "response_completed",
        "turn_finalized",
    )
    assert finalized_artifacts.turn is not None
    assert finalized_artifacts.turn.turn_index == 0
    assert finalized_artifacts.turn.status == "completed"
    assert finalized_artifacts.turn.terminal_message_index == 2
    assert finalized_artifacts.turn.text_chars == len("hello")
    assert finalized_artifacts.turn.cursor is None

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"second"}',
        )
    )
    await addon.websocket_message(flow)

    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 2

    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is not None

    provisional_entry = next(
        entry for entry in entries if entry.id == state.provisional_exchange_id
    )
    rotated_entry = next(entry for entry in entries if entry.id != state.provisional_exchange_id)
    assert provisional_entry.res is None
    assert provisional_entry.codex_turn is not None
    assert provisional_entry.codex_turn.status == "open"
    assert provisional_entry.codex_turn.message_range_start == 0
    assert provisional_entry.codex_turn.message_range_end == 0
    assert rotated_entry.id == finalized_entry.id
    assert rotated_entry.res is not None
    assert rotated_entry.res.stop_reason == "completed"

    provisional_artifacts = await storage.read_exchange(provisional_entry.id)
    assert provisional_artifacts.transport is not None
    assert [m.event_type for m in provisional_artifacts.transport.messages] == ["response.create"]
    assert provisional_artifacts.transport.close is None


async def test_addon_websocket_message_finalizes_turn_from_output_items() -> None:
    addon = TransportMattersAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"first"}',
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            (
                b'{"type":"response.output_item.done","item":{"id":"msg_01","type":"message","status":"completed","phase":"final_answer","role":"assistant","content":[{"type":"output_text","text":"assistant text"}]}}'
            ),
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            (
                b'{"type":"response.completed","response":{"id":"resp_01","model":"gpt-5-codex","status":"completed","usage":{"input_tokens":12,"input_tokens_details":{"cached_tokens":5},"output_tokens":7}}}'
            ),
        )
    )
    await addon.websocket_message(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.res is not None
    assert entry.res.stop_reason == "completed"
    assert entry.res.input_tokens == 12
    assert entry.res.cache_read_input_tokens == 5
    assert entry.res.output_tokens == 7
    assert entry.res.text_chars == len("assistant text")

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.response_ir is not None
    assert artifacts.response_ir.id == "resp_01"
    assert artifacts.response_ir.model == "codex/gpt-5-codex"
    assert artifacts.response_ir.content[0].type == "text"
    assert artifacts.response_ir.content[0].text == "assistant text"
    assert artifacts.response_ir.provider_extras["output_item_meta"][0]["phase"] == ("final_answer")


async def test_addon_websocket_message_finalizes_failed_turn() -> None:
    addon = TransportMattersAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"first"}',
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.failed","response":{"status":"failed"}}',
        )
    )
    await addon.websocket_message(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1

    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is None

    entry = entries[0]
    assert entry.res is not None
    assert entry.res.stop_reason == "failed"

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.transport is not None
    assert [m.event_type for m in artifacts.transport.messages] == [
        "response.create",
        "response.failed",
    ]
    assert artifacts.transport.close is None
    assert artifacts.events is not None
    assert tuple(event.kind for event in artifacts.events) == (
        "turn_started",
        "response_failed",
        "turn_finalized",
    )
    assert artifacts.turn is not None
    assert artifacts.turn.status == "failed"
    assert artifacts.turn.cursor is None
