"""Codex websocket response parsing into Manicure IR."""

from __future__ import annotations

import json
from typing import Any

from manicure.ir import (
    ContentBlock,
    InternalResponse,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    UnknownBlock,
    UsageStats,
)


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
        if event_type in {"response.completed", "response.failed"}:
            response = payload.get("response")
            if isinstance(response, dict):
                response_payload = response
            continue
        if event_type == "response.output_item.done":
            item = payload.get("item")
            if isinstance(item, dict):
                output_items.append(item)
            continue
        if event_type == "response.output_text.done":
            text = payload.get("text")
            if isinstance(text, str) and text:
                done_texts.append(text)
            continue
        if event_type == "response.output_text.delta":
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
        usage=_parse_usage(
            None if response_payload is None else response_payload.get("usage")
        ),
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
        return _normalise_model(model)
    if isinstance(default_model, str) and default_model:
        return _normalise_model(default_model)
    return "codex/unknown"


def _response_stop_reason(response_payload: dict[str, Any] | None) -> str | None:
    if response_payload is None:
        return None
    status = response_payload.get("status")
    if isinstance(status, str) and status:
        return status
    incomplete = response_payload.get("incomplete_details")
    if isinstance(incomplete, dict):
        reason = incomplete.get("reason")
        if isinstance(reason, str) and reason:
            return reason
    return None


def _parse_usage(raw_usage: object) -> UsageStats:
    if not isinstance(raw_usage, dict):
        return UsageStats()
    input_details = raw_usage.get("input_tokens_details")
    return UsageStats(
        input_tokens=_as_int(raw_usage.get("input_tokens")),
        output_tokens=_as_int(raw_usage.get("output_tokens")),
        cache_read_input_tokens=(
            _as_int(input_details.get("cached_tokens"))
            if isinstance(input_details, dict)
            else 0
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

        if item_type == "message":
            content.extend(_message_blocks(item))
            continue
        if item_type == "reasoning":
            content.append(_reasoning_block(item))
            continue
        if item_type in {"function_call", "custom_tool_call"}:
            tool_block = _tool_use_block(item)
            content.append(
                tool_block if tool_block is not None else UnknownBlock(raw=item)
            )
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
        entry_type = entry.get("type")
        if entry_type in {"output_text", "text"} and isinstance(entry.get("text"), str):
            blocks.append(TextBlock(text=entry["text"]))
            continue
        if entry_type == "refusal" and isinstance(entry.get("refusal"), str):
            blocks.append(TextBlock(text=entry["refusal"]))
            continue
        blocks.append(UnknownBlock(raw=entry))
    return blocks


def _reasoning_block(item: dict[str, Any]) -> ThinkingBlock:
    text_parts: list[str] = []
    summary = item.get("summary")
    if isinstance(summary, list):
        for entry in summary:
            if not isinstance(entry, dict):
                continue
            text = entry.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)

    provider_data = {
        key: value for key, value in item.items() if key not in {"summary"}
    }
    return ThinkingBlock(
        text="\n\n".join(text_parts),
        provider_data=provider_data or None,
    )


def _tool_use_block(item: dict[str, Any]) -> ToolUseBlock | None:
    call_id = item.get("call_id") or item.get("id")
    name = item.get("name")
    if not isinstance(call_id, str) or not call_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    arguments = item.get("arguments", item.get("input", {}))
    return ToolUseBlock(
        id=call_id,
        name=name,
        input=_parse_tool_arguments(arguments),
    )


def _parse_tool_arguments(arguments: object) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {"__raw_arguments__": arguments}
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    return {"value": arguments}


def _fallback_text_content(
    done_texts: list[str], deltas: list[str]
) -> list[ContentBlock]:
    if done_texts:
        return [TextBlock(text=text) for text in done_texts]
    if deltas:
        return [TextBlock(text="".join(deltas))]
    return []


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _normalise_model(model: str) -> str:
    if model.startswith("codex/"):
        return model
    return f"codex/{model}"
