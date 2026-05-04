"""Codex websocket transport helpers.

Tracks the ChatGPT authenticated Codex websocket handshake and the
active client request turn without pulling the later IR work into the
addon.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mitmproxy import http
    from mitmproxy.websocket import WebSocketMessage

    from transport_matters.ir import InternalResponse

from transport_matters.codex.protocol import (
    CODEX_NORMAL_CLOSE_CODES,
    codex_close_stop_reason,
    codex_payload_event_type,
    codex_terminal_status,
    codex_terminal_stop_reason,
    is_codex_turn_start,
)
from transport_matters.codex.response_parser import parse_codex_response_payloads
from transport_matters.storage.base import (
    ResStats,
    TransportArtifacts,
    TransportCloseArtifacts,
    TransportHeader,
    TransportMessageArtifact,
    TransportUpgradeArtifacts,
)
from transport_matters.transport_redaction import redact_transport_artifacts

CODEX_CHATGPT_HOST = "chatgpt.com"
CODEX_RESPONSES_PATH = "/backend-api/codex/responses"
CODEX_TRANSPORT_METADATA_KEY = "manicure_codex_transport"


@dataclass(slots=True)
class CodexUpgradeMetadata:
    scheme: str
    host: str
    path: str
    request_headers: tuple[tuple[str, str], ...]
    response_status_code: int | None
    response_headers: tuple[tuple[str, str], ...]


@dataclass(slots=True)
class CodexTransportState:
    upgrade: CodexUpgradeMetadata
    provisional_exchange_id: str | None = None
    finalized_exchange_id: str | None = None
    initial_client_frame: bytes | None = None
    initial_client_frame_text: str | None = None
    initial_client_frame_is_text: bool | None = None
    initial_client_frame_dropped: bool = False
    turn_start_message_index: int | None = None
    turn_client_messages_before: int = 0
    turn_server_messages_before: int = 0
    client_message_count: int = 0
    server_message_count: int = 0
    current_turn_index: int | None = None
    next_turn_index: int = 0


@dataclass(slots=True)
class CodexCloseSummary:
    close_code: int | None
    close_reason: str | None
    closed_by_client: bool | None
    initial_client_frame_captured: bool
    initial_client_frame_dropped: bool
    client_message_count: int
    server_message_count: int

    @property
    def is_normal(self) -> bool:
        return self.close_code in CODEX_NORMAL_CLOSE_CODES


def is_codex_websocket_flow(flow: http.HTTPFlow) -> bool:
    """Return True for the ChatGPT Codex websocket path."""
    request = getattr(flow, "request", None)
    if request is None:
        return False
    path = getattr(request, "path", "")
    return getattr(request, "host", "") == CODEX_CHATGPT_HOST and (
        path == CODEX_RESPONSES_PATH or path.startswith(f"{CODEX_RESPONSES_PATH}?")
    )


def get_codex_transport_state(flow: http.HTTPFlow) -> CodexTransportState | None:
    state = flow.metadata.get(CODEX_TRANSPORT_METADATA_KEY)
    if isinstance(state, CodexTransportState):
        return state
    return None


def ensure_codex_transport_state(flow: http.HTTPFlow) -> CodexTransportState | None:
    """Capture handshake metadata once and return the live transport state."""
    if not is_codex_websocket_flow(flow):
        return None

    state = get_codex_transport_state(flow)
    if state is not None:
        return state

    response = getattr(flow, "response", None)
    state = CodexTransportState(
        upgrade=CodexUpgradeMetadata(
            scheme=getattr(flow.request, "scheme", ""),
            host=getattr(flow.request, "host", ""),
            path=getattr(flow.request, "path", ""),
            request_headers=_snapshot_headers(flow.request.headers),
            response_status_code=getattr(response, "status_code", None),
            response_headers=_snapshot_headers(response.headers) if response else (),
        )
    )
    flow.metadata[CODEX_TRANSPORT_METADATA_KEY] = state
    return state


def record_codex_websocket_message(
    flow: http.HTTPFlow,
) -> tuple[CodexTransportState, WebSocketMessage, bool] | None:
    """Update Codex transport state for the newest websocket message."""
    state = ensure_codex_transport_state(flow)
    websocket = getattr(flow, "websocket", None)
    if state is None or websocket is None or not websocket.messages:
        return None

    message = websocket.messages[-1]
    if getattr(message, "timestamp", None) is None:
        message.timestamp = time.time()
    captured_initial = False

    if message.from_client:
        state.client_message_count += 1
        payload = _payload_json(_payload_text(message))
        if is_codex_turn_start(payload, from_client=True):
            state.initial_client_frame = bytes(message.content)
            state.initial_client_frame_is_text = message.is_text
            state.initial_client_frame_text = None
            if message.is_text:
                state.initial_client_frame_text = message.text
            state.initial_client_frame_dropped = False
            captured_initial = True
    else:
        state.server_message_count += 1

    return state, message, captured_initial


def is_codex_turn_terminal_message(message: WebSocketMessage) -> bool:
    """Return True when a server frame marks the end of the current turn."""
    payload = _payload_json(_payload_text(message))
    return codex_terminal_status(payload, from_client=message.from_client) is not None


def close_codex_transport(flow: http.HTTPFlow) -> CodexCloseSummary | None:
    state = get_codex_transport_state(flow)
    websocket = getattr(flow, "websocket", None)
    if state is None or websocket is None:
        return None
    if getattr(websocket, "timestamp_end", None) is None:
        websocket.timestamp_end = time.time()
    client_message_count = state.client_message_count
    server_message_count = state.server_message_count
    if state.turn_start_message_index is not None:
        client_message_count = max(
            0, client_message_count - state.turn_client_messages_before
        )
        server_message_count = max(
            0, server_message_count - state.turn_server_messages_before
        )
    return CodexCloseSummary(
        close_code=websocket.close_code,
        close_reason=websocket.close_reason,
        closed_by_client=websocket.closed_by_client,
        initial_client_frame_captured=state.initial_client_frame is not None,
        initial_client_frame_dropped=state.initial_client_frame_dropped,
        client_message_count=client_message_count,
        server_message_count=server_message_count,
    )


def mark_codex_initial_request_dropped(flow: http.HTTPFlow) -> None:
    """Record that the initial client frame was dropped at breakpoint release."""
    state = get_codex_transport_state(flow)
    if state is None or state.initial_client_frame is None:
        return
    state.initial_client_frame_dropped = True


def build_codex_transport_artifacts(
    flow: http.HTTPFlow,
    summary: CodexCloseSummary | None = None,
    *,
    message_end: int | None = None,
) -> TransportArtifacts | None:
    state = get_codex_transport_state(flow)
    websocket = getattr(flow, "websocket", None)
    if state is None:
        return None

    close = (
        TransportCloseArtifacts(
            ts=_transport_ts(getattr(websocket, "timestamp_end", None)),
            close_code=summary.close_code,
            close_reason=summary.close_reason,
            closed_by_client=summary.closed_by_client,
            initial_client_frame_captured=summary.initial_client_frame_captured,
            client_message_count=summary.client_message_count,
            server_message_count=summary.server_message_count,
        )
        if summary is not None
        else None
    )

    transport, _ = redact_transport_artifacts(
        TransportArtifacts(
            provider="codex",
            upgrade=TransportUpgradeArtifacts(
                scheme=state.upgrade.scheme,
                host=state.upgrade.host,
                path=state.upgrade.path,
                request_headers=_header_models(state.upgrade.request_headers),
                response_status_code=state.upgrade.response_status_code,
                response_headers=_header_models(state.upgrade.response_headers),
            ),
            close=close,
            messages=[]
            if websocket is None
            else [
                _message_artifact(message)
                for message in _turn_messages(websocket.messages, state, message_end)
            ],
        )
    )
    return transport


def build_codex_response_stats(
    flow: http.HTTPFlow,
    summary: CodexCloseSummary | None = None,
    *,
    message_end: int | None = None,
) -> ResStats:
    websocket = getattr(flow, "websocket", None)
    all_messages = getattr(websocket, "messages", None) or []
    state = get_codex_transport_state(flow)
    messages = (
        _turn_messages(all_messages, state, message_end)
        if state is not None
        else all_messages
    )
    stop_reason = _codex_stop_reason(messages, summary)
    return ResStats(
        stop_reason=stop_reason,
        text_chars=_codex_text_chars(messages),
        tool_calls=_codex_tool_call_count(messages),
    )


def build_codex_response_ir(
    flow: http.HTTPFlow,
    summary: CodexCloseSummary | None = None,
    *,
    message_end: int | None = None,
    default_model: str | None = None,
) -> InternalResponse | None:
    websocket = getattr(flow, "websocket", None)
    all_messages = getattr(websocket, "messages", None) or []
    state = get_codex_transport_state(flow)
    messages = (
        _turn_messages(all_messages, state, message_end)
        if state is not None
        else all_messages
    )
    return parse_codex_response_payloads(
        _server_json_messages(messages),
        default_model=default_model,
        default_stop_reason=_codex_stop_reason(messages, summary),
    )


def _snapshot_headers(headers: object) -> tuple[tuple[str, str], ...]:
    if headers is None or not hasattr(headers, "items"):
        return ()
    return tuple((key, value) for key, value in headers.items(multi=True))


def _header_models(headers: tuple[tuple[str, str], ...]) -> list[TransportHeader]:
    return [TransportHeader(name=name, value=value) for name, value in headers]


def _message_artifact(message: WebSocketMessage) -> TransportMessageArtifact:
    payload_text = _payload_text(message)
    payload_json = _payload_json(payload_text)
    event_type = _payload_event_type(payload_json)
    payload_base64 = (
        None if message.is_text else base64.b64encode(bytes(message.content)).decode()
    )
    return TransportMessageArtifact(
        ts=_transport_ts(getattr(message, "timestamp", None)),
        direction="client" if message.from_client else "server",
        is_text=bool(message.is_text),
        size_bytes=len(bytes(message.content)),
        dropped=bool(getattr(message, "dropped", False)),
        event_type=event_type,
        payload_text=payload_text,
        payload_json=payload_json,
        payload_base64=payload_base64,
    )


def _transport_ts(timestamp: float | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _payload_text(message: WebSocketMessage) -> str | None:
    if not message.is_text:
        return None
    try:
        return bytes(message.content).decode()
    except UnicodeDecodeError:
        return bytes(message.content).decode(errors="replace")


def _payload_json(payload_text: str | None) -> dict[str, Any] | list[Any] | None:
    if payload_text is None:
        return None
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, (dict, list)):
        return payload
    return None


def _message_event_type(message: WebSocketMessage) -> str | None:
    return _payload_event_type(_payload_json(_payload_text(message)))


def _payload_event_type(payload: dict[str, Any] | list[Any] | None) -> str | None:
    return codex_payload_event_type(payload)


def _turn_messages(
    messages: list[WebSocketMessage],
    state: CodexTransportState,
    message_end: int | None,
) -> list[WebSocketMessage]:
    start = state.turn_start_message_index or 0
    end = len(messages) if message_end is None else min(len(messages), message_end)
    if end < start:
        end = start
    return messages[start:end]


def _server_json_messages(messages: list[WebSocketMessage]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for message in messages:
        if message.from_client:
            continue
        payload = _payload_json(_payload_text(message))
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _codex_stop_reason(
    messages: list[WebSocketMessage],
    summary: CodexCloseSummary | None,
) -> str | None:
    payloads = _server_json_messages(messages)
    for payload in reversed(payloads):
        reason = codex_terminal_stop_reason(payload, from_client=False)
        if reason is not None:
            return reason
    if summary is None:
        return None
    return codex_close_stop_reason(summary.close_code)


def _codex_text_chars(messages: list[WebSocketMessage]) -> int:
    total = 0
    for payload in _server_json_messages(messages):
        event_type = payload.get("type")
        if not isinstance(event_type, str) or "output_text" not in event_type:
            continue
        delta = payload.get("delta")
        if isinstance(delta, str):
            total += len(delta)
    return total


def _codex_tool_call_count(messages: list[WebSocketMessage]) -> int:
    call_ids: set[str] = set()
    for payload in _server_json_messages(messages):
        _collect_tool_call_ids(payload, call_ids)
    return len(call_ids)


def _collect_tool_call_ids(node: Any, call_ids: set[str]) -> None:
    if isinstance(node, dict):
        node_type = node.get("type")
        if isinstance(node_type, str) and node_type in {
            "function_call",
            "custom_tool_call",
        }:
            call_id = node.get("call_id") or node.get("id")
            if isinstance(call_id, str) and call_id:
                call_ids.add(call_id)
        for value in node.values():
            _collect_tool_call_ids(value, call_ids)
        return
    if isinstance(node, list):
        for value in node:
            _collect_tool_call_ids(value, call_ids)
