"""Codex semantic event construction helpers."""

from typing import TYPE_CHECKING, Any, Literal, cast

from transport_matters.codex.derivation_contract import (
    CodexTurnDerivationContext,
    codex_event_id_for_seq,
)
from transport_matters.codex.events import (
    CodexOpenAssistantItem,
    CodexSemanticEvent,
    CodexTransportRef,
)
from transport_matters.codex.json_utils import json_text_length
from transport_matters.codex.protocol import codex_response_status_reason

if TYPE_CHECKING:
    from datetime import datetime


def append_codex_semantic_event(
    events: list[CodexSemanticEvent],
    *,
    next_seq: int,
    context: CodexTurnDerivationContext,
    source: Literal["client", "server", "proxy", "operator"],
    kind: str,
    ts: datetime,
    transport_ref: CodexTransportRef | None = None,
    data: dict[str, Any] | None = None,
) -> int:
    events.append(
        CodexSemanticEvent(
            event_id=codex_event_id_for_seq(next_seq),
            exchange_id=context.exchange_id,
            session_id=context.session_id,
            turn_id=context.turn_id,
            seq=next_seq,
            ts=ts,
            source=source,
            kind=cast("Any", kind),
            transport_ref=transport_ref,
            data=data or {},
            derivation_version=context.derivation_version,
        )
    )
    return next_seq + 1


def codex_tool_output_event_data(
    *,
    item: dict[str, Any],
    input_index: int,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "input_index": input_index,
        "item_type": str(item.get("type", "")),
        "output_chars": json_text_length(item.get("output")),
    }
    call_id = item.get("call_id")
    if isinstance(call_id, str) and call_id:
        data["call_id"] = call_id
    return data


def codex_assistant_item_event_data(item: dict[str, Any], *, text: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "item_type": str(item.get("type", "")),
        "text_chars": len(text),
    }
    item_id = item.get("id")
    if isinstance(item_id, str) and item_id:
        data["item_id"] = item_id
    phase = item.get("phase")
    if isinstance(phase, str) and phase:
        data["phase"] = phase
    role = item.get("role")
    if isinstance(role, str) and role:
        data["role"] = role
    return data


def codex_tool_call_event_data(
    item: dict[str, Any],
    *,
    arguments: str,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "item_type": str(item.get("type", "")),
        "arguments_chars": len(arguments),
    }
    call_id = item.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        call_id = item.get("id")
    if isinstance(call_id, str) and call_id:
        data["call_id"] = call_id
    item_id = item.get("id")
    if isinstance(item_id, str) and item_id:
        data["item_id"] = item_id
    tool_name = item.get("name")
    if isinstance(tool_name, str) and tool_name:
        data["tool_name"] = tool_name
    return data


def codex_terminal_event_data(
    *,
    payload: dict[str, Any],
    stop_reason: str,
) -> dict[str, Any]:
    data: dict[str, Any] = {"stop_reason": stop_reason}
    response = payload.get("response")
    if isinstance(response, dict):
        response_id = response.get("id")
        if isinstance(response_id, str) and response_id:
            data["response_id"] = response_id
        response_status = codex_response_status_reason(response)
        if isinstance(response_status, str) and response_status:
            data["response_status"] = response_status
    return data


def codex_turn_finalized_event_data(
    *,
    status: str,
    terminal_cause: str,
    stop_reason: str,
    text_chars: int,
    tool_calls: int,
    close_code: int | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "status": status,
        "terminal_cause": terminal_cause,
        "stop_reason": stop_reason,
        "text_chars": text_chars,
        "tool_calls": tool_calls,
    }
    if close_code is not None:
        data["close_code"] = close_code
    return data


def open_assistant_text_chars(
    open_assistant_items: dict[str, CodexOpenAssistantItem],
) -> int:
    return sum(len(item.text) for item in open_assistant_items.values())


__all__ = [
    "append_codex_semantic_event",
    "codex_assistant_item_event_data",
    "codex_terminal_event_data",
    "codex_tool_call_event_data",
    "codex_tool_output_event_data",
    "codex_turn_finalized_event_data",
    "open_assistant_text_chars",
]
