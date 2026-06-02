"""Codex websocket response parsing into Transport Matters IR."""

from __future__ import annotations

from typing import Any

from transport_matters.codex.protocol import (
    CODEX_MESSAGE_ITEM_TYPE,
    CODEX_MODEL_PREFIX,
    CODEX_OUTPUT_ITEM_DONE_EVENT_TYPE,
    CODEX_OUTPUT_TEXT_DELTA_EVENT_TYPE,
    CODEX_OUTPUT_TEXT_DONE_EVENT_TYPE,
    CODEX_REASONING_ITEM_TYPE,
    CODEX_TERMINAL_EVENT_TYPES,
    CODEX_TOOL_CALL_ITEM_TYPES,
    codex_reasoning_item_text,
    codex_response_status_reason,
    codex_text_from_content_entry,
    decode_tool_arguments,
)
from transport_matters.ir import (
    ContentBlock,
    InternalResponse,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    UnknownBlock,
    UsageStats,
)
from transport_matters.model_ids import normalise_model
from transport_matters.sse import iter_sse_data_objects


def parse_codex_response_sse(
    raw_body: bytes,
    *,
    default_model: str | None = None,
    default_stop_reason: str | None = None,
) -> InternalResponse | None:
    """Build an InternalResponse from a Codex HTTPS Responses SSE stream.

    The Codex HTTP fallback transport returns SSE events whose `data:`
    payloads share the same shape as the WebSocket frame payloads. The
    SSE envelope is the only difference; once payloads are extracted,
    the existing WS payload-to-IR builder produces the same result.
    """
    payloads = _parse_sse_event_payloads(raw_body)
    return parse_codex_response_payloads(
        payloads,
        default_model=default_model,
        default_stop_reason=default_stop_reason,
    )


def _parse_sse_event_payloads(raw_body: bytes) -> list[dict[str, Any]]:
    """Extract JSON event payloads from a Codex SSE byte stream.

    Each `data:` line is a single JSON object; multi-line `data:`
    continuations have not been observed on this transport. `[DONE]`
    sentinels, empty data lines, and undecodable JSON are skipped so
    a partial or noisy stream still yields whatever events parsed
    successfully.
    """
    return list(iter_sse_data_objects(raw_body))


def parse_codex_response_payloads(
    payloads: list[dict[str, Any]],
    *,
    default_model: str | None = None,
    default_stop_reason: str | None = None,
) -> InternalResponse | None:
    """Build an InternalResponse from Codex websocket server payloads."""
    response_payload: dict[str, Any] | None = None
    output_items: list[dict[str, Any]] = []
    done_texts: list[str] = []
    deltas: list[str] = []

    for payload in payloads:
        event_type = payload.get("type")
        if event_type in CODEX_TERMINAL_EVENT_TYPES:
            response = payload.get("response")
            if isinstance(response, dict):
                response_payload = response
            continue
        if event_type == CODEX_OUTPUT_ITEM_DONE_EVENT_TYPE:
            item = payload.get("item")
            if isinstance(item, dict):
                output_items.append(item)
            continue
        if event_type == CODEX_OUTPUT_TEXT_DONE_EVENT_TYPE:
            text = payload.get("text")
            if isinstance(text, str) and text:
                done_texts.append(text)
            continue
        if event_type == CODEX_OUTPUT_TEXT_DELTA_EVENT_TYPE:
            delta = payload.get("delta")
            if isinstance(delta, str) and delta:
                deltas.append(delta)

    if not output_items and response_payload is not None:
        raw_output = response_payload.get("output")
        if isinstance(raw_output, list):
            output_items = [item for item in raw_output if isinstance(item, dict)]

    content, output_item_meta = _parse_output_items(output_items)
    if not content:
        content = _fallback_text_content(done_texts, deltas)

    if response_payload is None and not content:
        return None

    provider_extras: dict[str, Any] = {}
    if output_item_meta:
        provider_extras["output_item_meta"] = output_item_meta
    error = None if response_payload is None else response_payload.get("error")
    if error not in (None, {}):
        provider_extras["error"] = error

    return InternalResponse(
        id=_response_id(response_payload, output_items),
        model=_response_model(response_payload, default_model),
        provider="codex",
        stop_reason=_response_stop_reason(response_payload) or default_stop_reason,
        usage=_parse_usage(None if response_payload is None else response_payload.get("usage")),
        content=content,
        provider_extras=provider_extras,
    )


def _response_id(
    response_payload: dict[str, Any] | None,
    output_items: list[dict[str, Any]],
) -> str:
    if response_payload is not None:
        response_id = response_payload.get("id")
        if isinstance(response_id, str) and response_id:
            return response_id
    for item in output_items:
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            return item_id
    return "codex-response"


def _response_model(
    response_payload: dict[str, Any] | None,
    default_model: str | None,
) -> str:
    model = None if response_payload is None else response_payload.get("model")
    if isinstance(model, str) and model:
        return normalise_model(model, CODEX_MODEL_PREFIX)
    if isinstance(default_model, str) and default_model:
        return normalise_model(default_model, CODEX_MODEL_PREFIX)
    return f"{CODEX_MODEL_PREFIX}unknown"


def _response_stop_reason(response_payload: dict[str, Any] | None) -> str | None:
    if response_payload is None:
        return None
    return codex_response_status_reason(response_payload)


def _parse_usage(raw_usage: object) -> UsageStats:
    if not isinstance(raw_usage, dict):
        return UsageStats()
    input_details = raw_usage.get("input_tokens_details")
    return UsageStats(
        input_tokens=_as_int(raw_usage.get("input_tokens")),
        output_tokens=_as_int(raw_usage.get("output_tokens")),
        cache_read_input_tokens=(
            _as_int(input_details.get("cached_tokens")) if isinstance(input_details, dict) else 0
        ),
        cache_creation_input_tokens=0,
    )


def _parse_output_items(
    output_items: list[dict[str, Any]],
) -> tuple[list[ContentBlock], list[dict[str, Any]]]:
    content: list[ContentBlock] = []
    output_item_meta: list[dict[str, Any]] = []

    for item in output_items:
        item_type = item.get("type")
        meta = _output_item_meta(item)
        if meta:
            output_item_meta.append(meta)

        if item_type == CODEX_MESSAGE_ITEM_TYPE:
            content.extend(_message_blocks(item))
            continue
        if item_type == CODEX_REASONING_ITEM_TYPE:
            content.append(_reasoning_block(item))
            continue
        if item_type in CODEX_TOOL_CALL_ITEM_TYPES:
            tool_block = _tool_use_block(item)
            content.append(tool_block if tool_block is not None else UnknownBlock(raw=item))
            continue
        content.append(UnknownBlock(raw=item))

    return content, output_item_meta


def _output_item_meta(item: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in ("id", "type", "status", "role", "phase", "call_id", "name"):
        value = item.get(key)
        if isinstance(value, str) and value:
            meta[key] = value
    return meta


def _message_blocks(item: dict[str, Any]) -> list[ContentBlock]:
    role = item.get("role")
    raw_content = item.get("content")
    if role != "assistant" or not isinstance(raw_content, list):
        return [UnknownBlock(raw=item)]

    blocks: list[ContentBlock] = []
    for entry in raw_content:
        if not isinstance(entry, dict):
            blocks.append(UnknownBlock(raw={"value": entry}))
            continue
        text = codex_text_from_content_entry(entry)
        if text is not None:
            blocks.append(TextBlock(text=text))
            continue
        blocks.append(UnknownBlock(raw=entry))
    return blocks


def _reasoning_block(item: dict[str, Any]) -> ThinkingBlock:
    provider_data = {key: value for key, value in item.items() if key not in {"summary"}}
    return ThinkingBlock(
        text=codex_reasoning_item_text(item),
        provider_data=provider_data or None,
    )


def _tool_use_block(item: dict[str, Any]) -> ToolUseBlock | None:
    call_id = item.get("call_id") or item.get("id")
    name = item.get("name")
    if item.get("type") == "tool_search_call" and name is None:
        name = "tool_search"
    if not isinstance(call_id, str) or not call_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    arguments = item.get("arguments", item.get("input", {}))
    return ToolUseBlock(
        id=call_id,
        name=name,
        input=decode_tool_arguments(arguments),
    )


def _fallback_text_content(done_texts: list[str], deltas: list[str]) -> list[ContentBlock]:
    if done_texts:
        return [TextBlock(text=text) for text in done_texts]
    if deltas:
        return [TextBlock(text="".join(deltas))]
    return []


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0
