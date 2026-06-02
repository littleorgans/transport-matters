"""Canonical Codex websocket payload and boundary helpers."""

from __future__ import annotations

import json
from typing import Any, Literal

from transport_matters.codex.events import CodexOpenAssistantItem, CodexOpenToolCall
from transport_matters.codex.json_utils import compact_json

type CodexTerminalStatus = Literal["completed", "failed"]

CODEX_MODEL_PREFIX = "codex/"
CODEX_TURN_START_EVENT_TYPE = "response.create"
CODEX_OUTPUT_ITEM_ADDED_EVENT_TYPE = "response.output_item.added"
CODEX_OUTPUT_ITEM_DONE_EVENT_TYPE = "response.output_item.done"
CODEX_OUTPUT_TEXT_DELTA_EVENT_TYPE = "response.output_text.delta"
CODEX_OUTPUT_TEXT_DONE_EVENT_TYPE = "response.output_text.done"
CODEX_FUNCTION_CALL_ARGUMENTS_DELTA_EVENT_TYPE = "response.function_call_arguments.delta"
CODEX_FUNCTION_CALL_ARGUMENTS_DONE_EVENT_TYPE = "response.function_call_arguments.done"
CODEX_ANONYMOUS_ASSISTANT_ITEM_ID = "__anonymous_assistant__"
CODEX_ASSISTANT_ITEM_COMPLETED_EVENT_TYPE = CODEX_OUTPUT_ITEM_DONE_EVENT_TYPE
CODEX_TERMINAL_STATUS_BY_EVENT_TYPE: dict[str, CodexTerminalStatus] = {
    "response.completed": "completed",
    "response.failed": "failed",
}
CODEX_TERMINAL_EVENT_TYPES = frozenset(CODEX_TERMINAL_STATUS_BY_EVENT_TYPE)
CODEX_INTERRUPTED_STATUS = "interrupted"
CODEX_MESSAGE_ITEM_TYPE = "message"
CODEX_NORMAL_CLOSE_CODES = frozenset({1000, 1001})
CODEX_REASONING_ITEM_TYPE = "reasoning"
CODEX_INPUT_TEXT_TYPE = "input_text"
CODEX_OUTPUT_TEXT_TYPE = "output_text"
CODEX_TEXT_TYPE = "text"
CODEX_REFUSAL_TYPE = "refusal"
CODEX_IMAGE_TYPE = "input_image"
CODEX_INPUT_TEXT_TYPES = frozenset({CODEX_INPUT_TEXT_TYPE, CODEX_TEXT_TYPE})
CODEX_OUTPUT_TEXT_TYPES = frozenset({CODEX_OUTPUT_TEXT_TYPE, CODEX_TEXT_TYPE})
CODEX_PRESERVED_TEXT_TYPES = (
    CODEX_INPUT_TEXT_TYPES | CODEX_OUTPUT_TEXT_TYPES | frozenset({CODEX_REFUSAL_TYPE})
)
CODEX_TOOL_CALL_ITEM_TYPES = frozenset({"function_call", "custom_tool_call", "tool_search_call"})
CODEX_TOOL_OUTPUT_ITEM_TYPES = frozenset(
    {"function_call_output", "custom_tool_call_output", "tool_search_output"}
)
RAW_TOOL_ARGUMENTS_KEY = "__raw_arguments__"


def codex_payload_event_type(payload: object) -> str | None:
    if isinstance(payload, dict):
        event_type = payload.get("type")
        if isinstance(event_type, str):
            return event_type
    return None


def is_codex_turn_start(payload: object, *, from_client: bool) -> bool:
    return from_client and codex_payload_event_type(payload) == CODEX_TURN_START_EVENT_TYPE


def codex_terminal_status(
    payload: object,
    *,
    from_client: bool,
) -> CodexTerminalStatus | None:
    if from_client:
        return None
    event_type = codex_payload_event_type(payload)
    if event_type is None:
        return None
    return CODEX_TERMINAL_STATUS_BY_EVENT_TYPE.get(event_type)


def codex_terminal_stop_reason(
    payload: object,
    *,
    from_client: bool,
) -> str | None:
    status = codex_terminal_status(payload, from_client=from_client)
    if status is None:
        return None
    if not isinstance(payload, dict):
        return status
    reason = codex_response_status_reason(payload.get("response"))
    return reason or status


def codex_response_status_reason(response: object) -> str | None:
    if not isinstance(response, dict):
        return None
    status = response.get("status")
    if isinstance(status, str) and status:
        return status
    incomplete = response.get("incomplete_details")
    if isinstance(incomplete, dict):
        reason = incomplete.get("reason")
        if isinstance(reason, str) and reason:
            return reason
    return None


def codex_assistant_completed_item(payload: object) -> dict[str, Any] | None:
    if codex_payload_event_type(payload) != CODEX_ASSISTANT_ITEM_COMPLETED_EVENT_TYPE:
        return None
    if not isinstance(payload, dict):
        return None
    item = payload.get("item")
    if not isinstance(item, dict):
        return None
    if item.get("type") != CODEX_MESSAGE_ITEM_TYPE:
        return None
    if item.get("role") != "assistant":
        return None
    if item.get("status") != "completed":
        return None
    return item


def is_codex_assistant_item_completion(payload: object) -> bool:
    return codex_assistant_completed_item(payload) is not None


def codex_reasoning_completed_item(payload: object) -> dict[str, Any] | None:
    if codex_payload_event_type(payload) != CODEX_OUTPUT_ITEM_DONE_EVENT_TYPE:
        return None
    if not isinstance(payload, dict):
        return None
    item = payload.get("item")
    if not isinstance(item, dict):
        return None
    if item.get("type") != CODEX_REASONING_ITEM_TYPE:
        return None
    return item


def codex_tool_call_completed_item(payload: object) -> dict[str, Any] | None:
    if codex_payload_event_type(payload) != CODEX_OUTPUT_ITEM_DONE_EVENT_TYPE:
        return None
    if not isinstance(payload, dict):
        return None
    item = payload.get("item")
    if not isinstance(item, dict):
        return None
    item_type = item.get("type")
    if item_type not in CODEX_TOOL_CALL_ITEM_TYPES:
        return None
    return item


def codex_iter_tool_output_items(
    payload: dict[str, Any] | None,
) -> tuple[tuple[int, dict[str, Any]], ...]:
    if payload is None:
        return ()
    raw_input = payload.get("input")
    if not isinstance(raw_input, list):
        return ()
    items: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(raw_input):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in CODEX_TOOL_OUTPUT_ITEM_TYPES:
            items.append((index, item))
    return tuple(items)


def codex_update_open_assistant_items(
    *,
    payload: dict[str, Any],
    open_assistant_items: dict[str, CodexOpenAssistantItem],
) -> None:
    event_type = codex_payload_event_type(payload)
    if event_type == CODEX_OUTPUT_TEXT_DELTA_EVENT_TYPE:
        item_id = payload.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            item_id = CODEX_ANONYMOUS_ASSISTANT_ITEM_ID
        delta = payload.get("delta")
        if isinstance(delta, str) and delta:
            current = open_assistant_items.get(item_id, CodexOpenAssistantItem()).text
            open_assistant_items[item_id] = CodexOpenAssistantItem(text=current + delta)
        return
    if event_type == CODEX_OUTPUT_TEXT_DONE_EVENT_TYPE:
        item_id = payload.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            item_id = CODEX_ANONYMOUS_ASSISTANT_ITEM_ID
        text = payload.get("text")
        if isinstance(text, str):
            open_assistant_items[item_id] = CodexOpenAssistantItem(text=text)
        return
    if event_type == CODEX_OUTPUT_ITEM_ADDED_EVENT_TYPE:
        item = payload.get("item")
        item_id = item.get("id") if isinstance(item, dict) else None
        if (
            isinstance(item, dict)
            and item.get("type") == CODEX_MESSAGE_ITEM_TYPE
            and isinstance(item_id, str)
            and item_id
        ):
            open_assistant_items.setdefault(item_id, CodexOpenAssistantItem())


def codex_update_open_tool_calls(
    *,
    payload: dict[str, Any],
    open_tool_calls: dict[str, CodexOpenToolCall],
) -> None:
    event_type = codex_payload_event_type(payload)
    if event_type == CODEX_OUTPUT_ITEM_ADDED_EVENT_TYPE:
        item = payload.get("item")
        if not isinstance(item, dict):
            return
        call_key = codex_tool_call_key(item)
        if call_key is None:
            return
        open_tool_calls[call_key] = CodexOpenToolCall(
            arguments=codex_tool_call_arguments_text(item)
        )
        return
    if event_type == CODEX_FUNCTION_CALL_ARGUMENTS_DELTA_EVENT_TYPE:
        call_key = codex_tool_call_key(payload)
        delta = payload.get("delta")
        if call_key is None or not isinstance(delta, str):
            return
        current = open_tool_calls.get(call_key, CodexOpenToolCall()).arguments
        open_tool_calls[call_key] = CodexOpenToolCall(arguments=current + delta)
        return
    if event_type == CODEX_FUNCTION_CALL_ARGUMENTS_DONE_EVENT_TYPE:
        call_key = codex_tool_call_key(payload)
        arguments = payload.get("arguments")
        if call_key is None or not isinstance(arguments, str):
            return
        open_tool_calls[call_key] = CodexOpenToolCall(arguments=arguments)


def codex_tool_call_key(node: dict[str, Any]) -> str | None:
    call_id = node.get("call_id")
    if isinstance(call_id, str) and call_id:
        return call_id
    item_id = node.get("item_id") or node.get("id")
    if isinstance(item_id, str) and item_id:
        return item_id
    return None


def codex_tool_call_arguments_text(item: dict[str, Any]) -> str:
    arguments = item.get("arguments")
    if isinstance(arguments, str):
        return arguments
    if arguments is None:
        return ""
    return compact_json(arguments)


def decode_tool_arguments(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {RAW_TOOL_ARGUMENTS_KEY: value}
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    return {"value": value}


def codex_text_from_content_entry(entry: dict[str, Any]) -> str | None:
    entry_type = entry.get("type")
    text = entry.get("text")
    if entry_type in CODEX_OUTPUT_TEXT_TYPES and isinstance(text, str):
        return text
    refusal = entry.get("refusal")
    if entry_type == CODEX_REFUSAL_TYPE and isinstance(refusal, str):
        return refusal
    return None


def codex_assistant_item_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for entry in content:
        if not isinstance(entry, dict):
            continue
        text = codex_text_from_content_entry(entry)
        if text is not None:
            parts.append(text)
    return "".join(parts)


def codex_reasoning_item_text(item: dict[str, Any]) -> str:
    summary = item.get("summary")
    if not isinstance(summary, list):
        return ""
    parts: list[str] = []
    for entry in summary:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n\n".join(parts)


def codex_close_stop_reason(close_code: int | None) -> str:
    if close_code in CODEX_NORMAL_CLOSE_CODES:
        return "ws_closed"
    if close_code is not None:
        return f"ws_close_{close_code}"
    return "ws_closed"


__all__ = [
    "CODEX_ANONYMOUS_ASSISTANT_ITEM_ID",
    "CODEX_ASSISTANT_ITEM_COMPLETED_EVENT_TYPE",
    "CODEX_FUNCTION_CALL_ARGUMENTS_DELTA_EVENT_TYPE",
    "CODEX_FUNCTION_CALL_ARGUMENTS_DONE_EVENT_TYPE",
    "CODEX_INTERRUPTED_STATUS",
    "CODEX_MESSAGE_ITEM_TYPE",
    "CODEX_NORMAL_CLOSE_CODES",
    "CODEX_OUTPUT_ITEM_ADDED_EVENT_TYPE",
    "CODEX_OUTPUT_ITEM_DONE_EVENT_TYPE",
    "CODEX_OUTPUT_TEXT_DELTA_EVENT_TYPE",
    "CODEX_OUTPUT_TEXT_DONE_EVENT_TYPE",
    "CODEX_REASONING_ITEM_TYPE",
    "CODEX_TERMINAL_EVENT_TYPES",
    "CODEX_TERMINAL_STATUS_BY_EVENT_TYPE",
    "CODEX_TOOL_CALL_ITEM_TYPES",
    "CODEX_TOOL_OUTPUT_ITEM_TYPES",
    "CODEX_TURN_START_EVENT_TYPE",
    "CodexTerminalStatus",
    "codex_assistant_completed_item",
    "codex_assistant_item_text",
    "codex_close_stop_reason",
    "codex_iter_tool_output_items",
    "codex_payload_event_type",
    "codex_reasoning_completed_item",
    "codex_reasoning_item_text",
    "codex_response_status_reason",
    "codex_terminal_status",
    "codex_terminal_stop_reason",
    "codex_tool_call_arguments_text",
    "codex_tool_call_completed_item",
    "codex_tool_call_key",
    "codex_update_open_assistant_items",
    "codex_update_open_tool_calls",
    "is_codex_assistant_item_completion",
    "is_codex_turn_start",
]
