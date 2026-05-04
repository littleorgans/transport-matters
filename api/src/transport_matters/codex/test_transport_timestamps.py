from __future__ import annotations

from datetime import UTC, datetime

from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from transport_matters.codex.transport import (
    build_codex_transport_artifacts,
    close_codex_transport,
    ensure_codex_transport_state,
    record_codex_websocket_message,
)

from .test_transport_support import _codex_flow


def test_build_codex_transport_artifacts_persists_message_and_close_timestamps() -> (
    None
):
    flow = _codex_flow()
    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert flow.websocket is not None
    flow.websocket.messages.clear()

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex"}',
            timestamp=1776572041.25,
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
            timestamp=1776572042.5,
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "done"
    flow.websocket.closed_by_client = False
    flow.websocket.timestamp_end = 1776572043.75

    summary = close_codex_transport(flow)
    transport = build_codex_transport_artifacts(flow, summary)

    assert transport is not None
    assert [message.ts for message in transport.messages] == [
        datetime.fromtimestamp(1776572041.25, tz=UTC),
        datetime.fromtimestamp(1776572042.5, tz=UTC),
    ]
    assert transport.close is not None
    assert transport.close.ts == datetime.fromtimestamp(1776572043.75, tz=UTC)
