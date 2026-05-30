"""Preserved raw Codex input item reconciliation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from transport_matters.codex.protocol import (
    CODEX_IMAGE_TYPE,
    CODEX_INPUT_TEXT_TYPE,
    CODEX_OUTPUT_TEXT_TYPE,
    CODEX_PRESERVED_TEXT_TYPES,
    CODEX_REFUSAL_TYPE,
)


@dataclass(slots=True)
class SerializedInputItem:
    kind: str
    payload: dict[str, Any]
    original_index: int | None = None


def parse_preserved_input_item_raw(raw: object) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Codex input_item_raw must be a list")

    entries: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Codex input_item_raw entries must be objects")
        index = entry.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("Codex input_item_raw index must be an integer")
        entries.append({"index": index, "raw": entry.get("raw")})
    return entries


def apply_preserved_input_items(
    items: list[SerializedInputItem],
    preserved_input: list[dict[str, Any]],
) -> None:
    pending_by_kind: dict[str, list[dict[str, Any]]] = {}
    for entry in preserved_input:
        kind = input_item_kind(entry["raw"])
        pending_by_kind.setdefault(kind, []).append(entry)

    for item in items:
        candidates = pending_by_kind.get(item.kind)
        if not candidates:
            continue
        raw_entry = _pop_matching_preserved_input(item.kind, item.payload, candidates)
        if raw_entry is None:
            continue
        item.payload = _merge_input_item_raw(item.kind, raw_entry["raw"], item.payload)
        item.original_index = raw_entry["index"]

    leftover = min(
        (entry for entries in pending_by_kind.values() for entry in entries),
        key=lambda entry: entry["index"],
        default=None,
    )
    if leftover is not None:
        raise ValueError(
            "Codex serializer could not reconcile preserved raw input item "
            f"at index {leftover['index']}"
        )


def input_item_kind(raw: object) -> str:
    if not isinstance(raw, dict):
        return "raw"
    item_type = raw.get("type")
    if item_type == "function_call":
        return "tool_use"
    if item_type in {
        "function_call_output",
        "custom_tool_call_output",
        "tool_search_output",
    }:
        return f"tool_result:{item_type}"
    if item_type == "reasoning":
        return "reasoning"
    role = raw.get("role")
    if isinstance(role, str):
        return f"message:{role}"
    return f"message:{raw.get('role', 'user')}"


def looks_like_input_item(raw: object) -> bool:
    return isinstance(raw, dict) and (
        "role" in raw
        or raw.get("type")
        in {
            "function_call",
            "function_call_output",
            "custom_tool_call_output",
            "tool_search_output",
            "reasoning",
        }
    )


def materialize_input_items(items: list[SerializedInputItem]) -> list[dict[str, Any]]:
    positioned: dict[int, dict[str, Any]] = {}
    unpositioned: list[dict[str, Any]] = []

    for item in items:
        if item.original_index is None:
            unpositioned.append(item.payload)
            continue
        if item.original_index in positioned:
            raise ValueError(
                "Codex serializer saw duplicate preserved input index "
                f"{item.original_index}"
            )
        positioned[item.original_index] = item.payload

    total = max(len(items), (max(positioned) + 1) if positioned else 0)
    result: list[dict[str, Any]] = []
    cursor = 0

    for index in range(total):
        if index in positioned:
            result.append(positioned[index])
            continue
        if cursor >= len(unpositioned):
            raise ValueError("Codex serializer could not materialize input ordering")
        result.append(unpositioned[cursor])
        cursor += 1

    result.extend(unpositioned[cursor:])
    return result


def _merge_input_item_raw(
    kind: str,
    raw: object,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return payload
    if kind.startswith("message:"):
        return _merge_message_item(raw, payload)
    if kind == "tool_use":
        merged = dict(raw)
        merged["call_id"] = payload["call_id"]
        merged["name"] = payload["name"]
        merged["arguments"] = payload["arguments"]
        return merged
    if kind.startswith("tool_result:"):
        merged = dict(raw)
        merged["call_id"] = payload["call_id"]
        if kind == "tool_result:tool_search_output":
            merged["tools"] = payload.get("tools", [])
            return merged
        merged["output"] = payload["output"]
        if payload.get("is_error"):
            merged["is_error"] = True
        else:
            merged.pop("is_error", None)
        return merged
    if kind == "reasoning":
        merged = dict(raw)
        merged.update(payload)
        return merged
    return payload


def _pop_matching_preserved_input(
    kind: str,
    payload: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    match_key = _preserved_input_match_key(kind, payload)
    if match_key is None:
        return candidates.pop(0) if candidates else None

    match_name, match_value = match_key
    for index, entry in enumerate(candidates):
        raw = entry.get("raw")
        if isinstance(raw, dict) and raw.get(match_name) == match_value:
            return candidates.pop(index)
    return None


def _preserved_input_match_key(
    kind: str,
    payload: dict[str, Any],
) -> tuple[str, str] | None:
    if kind == "tool_use" or kind.startswith("tool_result:"):
        value = payload.get("call_id")
        if isinstance(value, str):
            return ("call_id", value)
        return None

    value = payload.get("id")
    if isinstance(value, str):
        return ("id", value)
    return None


def _merge_message_item(
    raw: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(raw)
    merged["role"] = payload["role"]

    raw_content = raw.get("content")
    payload_content = payload.get("content")
    if (
        isinstance(raw_content, list)
        and isinstance(payload_content, list)
        and len(raw_content) == len(payload_content)
    ):
        merged["content"] = [
            _merge_message_content_item(raw_item, serialized_item)
            for raw_item, serialized_item in zip(
                raw_content, payload_content, strict=True
            )
        ]
    else:
        merged["content"] = payload_content

    return merged


def _merge_message_content_item(
    raw: object,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return payload

    raw_type = raw.get("type")
    payload_type = payload.get("type")
    if payload_type == CODEX_IMAGE_TYPE and raw_type == CODEX_IMAGE_TYPE:
        merged = dict(raw)
        for key, value in payload.items():
            if key != "type":
                merged[key] = value
        return merged
    if (
        payload_type in {CODEX_INPUT_TEXT_TYPE, CODEX_OUTPUT_TEXT_TYPE}
        and raw_type in CODEX_PRESERVED_TEXT_TYPES
    ):
        merged = dict(raw)
        if raw_type == CODEX_REFUSAL_TYPE:
            merged["refusal"] = payload["text"]
            merged.pop("text", None)
        else:
            merged["text"] = payload["text"]
        return merged
    return payload
