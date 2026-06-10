"""Override model, store, and apply logic for the Transport Matters pipeline.

Replaces the rules engine with a direct override model. Users edit
request content in the breakpoint editor; edits produce typed overrides
that persist across exchanges within a session.

This module coordinates override operation helpers and exposes the public
override model, store, and application entrypoints.
"""

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from transport_matters.override_audit import (
    OverrideAudit,
    OverrideAuditEntry,
    count_chars_parts,
    identity_audit,
)
from transport_matters.override_ops_messages import (
    apply_message_block_toggle,
    apply_message_text,
    apply_system_part_text,
    apply_system_part_toggle,
    apply_tool_description,
    apply_tool_toggle,
    apply_truncate_tool_result,
    codex_has_tool_result_only_turn,
    sanitize_curated_messages,
)
from transport_matters.override_ops_metadata import (
    apply_provider_extras_set,
    apply_sampling_set,
)
from transport_matters.override_state import OverrideStore, get_store
from transport_matters.override_targets import (
    adjust_blk_index,
    adjust_system_index,
    parse_message_target,
    parse_provider_extras_key,
    parse_sampling_field,
    parse_system_index,
    parse_tool_name,
    parse_tool_result_id,
)

if TYPE_CHECKING:
    from transport_matters.ir import InternalRequest

__all__ = [
    "Override",
    "OverrideAudit",
    "OverrideAuditEntry",
    "OverrideKind",
    "OverrideStore",
    "apply_overrides",
    "count_chars_parts",
    "get_store",
    "identity_audit",
]

# ── Override types ────────────────────────────────────────────────

OverrideKind = Literal[
    "tool_toggle",
    "tool_description",
    "system_part_toggle",
    "system_part_text",
    "message_block_toggle",
    "message_text",
    "truncate_tool_result",
    "sampling_set",
    "provider_extras_set",
]

# Fixed priority order: toggles before rewrites, global before targeted.
# Sampling/provider_extras sit last. They don't touch char counts, so ordering
# vs earlier kinds is irrelevant for correctness; placing them at the tail
# keeps the audit ledger readable (content edits first, knob edits last).
_PRIORITY: dict[str, int] = {
    "tool_toggle": 1,
    "tool_description": 2,
    "system_part_toggle": 3,
    "system_part_text": 4,
    "truncate_tool_result": 5,
    "message_block_toggle": 6,
    "message_text": 7,
    "sampling_set": 8,
    "provider_extras_set": 9,
}


class Override(BaseModel):
    """Single user override. Frozen after creation; replaced on update."""

    model_config = ConfigDict(frozen=True)

    kind: OverrideKind
    target: str
    value: str | bool | int | None
    # bool   -> toggles (tool_toggle, system_part_toggle, message_block_toggle)
    # str    -> rewrites (tool_description, system_part_text, message_text),
    #           and JSON-encoded payloads for sampling_set / provider_extras_set
    #           (JSON encoding lets a single scalar `value` field carry floats,
    #           lists, and objects without widening the Override schema)
    # int    -> truncation limits (truncate_tool_result)
    # None   -> remove this override from the store


# ── Apply pipeline ───────────────────────────────────────────────


def _decode_json_payload(value: str) -> tuple[bool, object]:
    try:
        return True, json.loads(value)
    except json.JSONDecodeError:
        return False, None


@dataclass
class _OverrideApplyContext:
    original_ir: InternalRequest
    current_ir: InternalRequest
    removed_system_indices: set[int] = field(default_factory=set)
    removed_blk_indices: dict[int, set[int]] = field(default_factory=dict)


@dataclass(frozen=True)
class _OverrideApplyResult:
    applied: bool = False
    chars_delta: int = 0
    curated_value: str | None = None


_NOT_APPLIED = _OverrideApplyResult()


def apply_overrides(
    overrides: list[Override],
    ir: InternalRequest,
) -> tuple[InternalRequest, OverrideAudit]:
    """Apply all overrides to an IR in fixed priority order. Returns new IR + audit.

    Index-based overrides (``system_part_*``, ``message_text``) always refer
    to positions in the *original* IR. When earlier overrides remove items
    (``system_part_toggle``, ``message_block_toggle``), later overrides have
    their target indices adjusted so they still hit the intended item.
    """
    sys_before, tools_before, msgs_before = count_chars_parts(ir)
    context = _OverrideApplyContext(original_ir=ir, current_ir=ir)
    entries = [
        _apply_override(context, override)
        for override in sorted(overrides, key=lambda o: _PRIORITY[o.kind])
    ]

    _sanitize_current_ir(context)
    sys_after, tools_after, msgs_after = count_chars_parts(context.current_ir)
    audit = _build_override_audit(
        entries=entries,
        before=(sys_before, tools_before, msgs_before),
        after=(sys_after, tools_after, msgs_after),
    )
    return context.current_ir, audit


def _apply_override(
    context: _OverrideApplyContext,
    override: Override,
) -> OverrideAuditEntry:
    result = _apply_override_value(context, override)
    return OverrideAuditEntry(
        kind=override.kind,
        target=override.target,
        applied=result.applied,
        chars_delta=result.chars_delta,
        curated_value=result.curated_value,
    )


def _apply_override_value(
    context: _OverrideApplyContext,
    override: Override,
) -> _OverrideApplyResult:
    if override.kind == "tool_toggle":
        return _apply_tool_toggle(context, override.target, override.value)
    if override.kind == "tool_description":
        return _apply_tool_description(context, override.target, override.value)
    if override.kind == "system_part_toggle":
        return _apply_system_part_toggle(context, override.target, override.value)
    if override.kind == "system_part_text":
        return _apply_system_part_text(context, override.target, override.value)
    if override.kind == "truncate_tool_result":
        return _apply_truncate_tool_result(context, override.target, override.value)
    if override.kind == "message_block_toggle":
        return _apply_message_block_toggle(context, override.target, override.value)
    if override.kind == "message_text":
        return _apply_message_text(context, override.target, override.value)
    if override.kind == "sampling_set":
        return _apply_sampling_override(context, override.target, override.value)
    if override.kind == "provider_extras_set":
        return _apply_provider_extras_override(context, override.target, override.value)
    return _NOT_APPLIED


def _apply_tool_toggle(
    context: _OverrideApplyContext,
    target: str,
    value: str | bool | int | None,
) -> _OverrideApplyResult:
    tool_name = parse_tool_name(target)
    if tool_name is None or not isinstance(value, bool):
        return _NOT_APPLIED
    if value:
        return _OverrideApplyResult(
            applied=any(t.name == tool_name for t in context.original_ir.tools)
        )
    return _mutate_current_ir(
        context,
        apply_tool_toggle(context.current_ir, tool_name, value),
    )


def _apply_tool_description(
    context: _OverrideApplyContext,
    target: str,
    value: str | bool | int | None,
) -> _OverrideApplyResult:
    tool_name = parse_tool_name(target)
    if tool_name is None or not isinstance(value, str):
        return _NOT_APPLIED
    return _mutate_current_ir(
        context,
        apply_tool_description(context.current_ir, tool_name, value),
        curated_value=value,
    )


def _apply_system_part_toggle(
    context: _OverrideApplyContext,
    target: str,
    value: str | bool | int | None,
) -> _OverrideApplyResult:
    original_index = parse_system_index(target)
    if original_index is None or not isinstance(value, bool):
        return _NOT_APPLIED
    if value:
        return _OverrideApplyResult(applied=0 <= original_index < len(context.original_ir.system))
    if original_index in context.removed_system_indices:
        return _NOT_APPLIED

    adjusted = adjust_system_index(original_index, context.removed_system_indices)
    result = _mutate_current_ir(
        context,
        apply_system_part_toggle(context.current_ir, adjusted, value),
    )
    if result.applied:
        context.removed_system_indices.add(original_index)
    return result


def _apply_system_part_text(
    context: _OverrideApplyContext,
    target: str,
    value: str | bool | int | None,
) -> _OverrideApplyResult:
    original_index = parse_system_index(target)
    if (
        original_index is None
        or not isinstance(value, str)
        or original_index in context.removed_system_indices
    ):
        return _NOT_APPLIED

    adjusted = adjust_system_index(original_index, context.removed_system_indices)
    return _mutate_current_ir(
        context,
        apply_system_part_text(context.current_ir, adjusted, value),
        curated_value=value,
    )


def _apply_truncate_tool_result(
    context: _OverrideApplyContext,
    target: str,
    value: str | bool | int | None,
) -> _OverrideApplyResult:
    tool_use_id = parse_tool_result_id(target)
    if tool_use_id is None or not isinstance(value, int) or value <= 0:
        return _NOT_APPLIED

    context.current_ir, chars_delta, applied, curated_value = apply_truncate_tool_result(
        context.current_ir,
        tool_use_id,
        value,
    )
    return _OverrideApplyResult(
        applied=applied,
        chars_delta=chars_delta,
        curated_value=curated_value,
    )


def _apply_message_block_toggle(
    context: _OverrideApplyContext,
    target: str,
    value: str | bool | int | None,
) -> _OverrideApplyResult:
    parsed = parse_message_target(target)
    if parsed is None or not isinstance(value, bool):
        return _NOT_APPLIED

    msg_idx, original_blk_idx = parsed
    if value:
        return _OverrideApplyResult(
            applied=0 <= msg_idx < len(context.original_ir.messages)
            and 0 <= original_blk_idx < len(context.original_ir.messages[msg_idx].content)
        )

    adjusted_blk = adjust_blk_index(msg_idx, original_blk_idx, context.removed_blk_indices)
    if adjusted_blk is None:
        return _NOT_APPLIED

    result = _mutate_current_ir(
        context,
        apply_message_block_toggle(context.current_ir, msg_idx, adjusted_blk),
    )
    if result.applied:
        context.removed_blk_indices.setdefault(msg_idx, set()).add(original_blk_idx)
    return result


def _apply_message_text(
    context: _OverrideApplyContext,
    target: str,
    value: str | bool | int | None,
) -> _OverrideApplyResult:
    parsed = parse_message_target(target)
    if parsed is None or not isinstance(value, str):
        return _NOT_APPLIED

    msg_idx, original_blk_idx = parsed
    adjusted_blk = adjust_blk_index(msg_idx, original_blk_idx, context.removed_blk_indices)
    if adjusted_blk is None:
        return _NOT_APPLIED
    return _mutate_current_ir(
        context,
        apply_message_text(context.current_ir, msg_idx, adjusted_blk, value),
        curated_value=value,
    )


def _apply_sampling_override(
    context: _OverrideApplyContext,
    target: str,
    value: str | bool | int | None,
) -> _OverrideApplyResult:
    field_name = parse_sampling_field(target)
    if field_name is None or not isinstance(value, str):
        return _NOT_APPLIED

    decoded, parsed_value = _decode_json_payload(value)
    if not decoded:
        return _NOT_APPLIED
    return _mutate_current_ir(
        context,
        apply_sampling_set(context.current_ir, field_name, parsed_value),
    )


def _apply_provider_extras_override(
    context: _OverrideApplyContext,
    target: str,
    value: str | bool | int | None,
) -> _OverrideApplyResult:
    key = parse_provider_extras_key(target)
    if key is None or not isinstance(value, str):
        return _NOT_APPLIED

    decoded, parsed_value = _decode_json_payload(value)
    if not decoded:
        return _NOT_APPLIED
    return _mutate_current_ir(
        context,
        apply_provider_extras_set(context.current_ir, key, parsed_value),
    )


def _mutate_current_ir(
    context: _OverrideApplyContext,
    mutation: tuple[InternalRequest, int, bool],
    *,
    curated_value: str | None = None,
) -> _OverrideApplyResult:
    context.current_ir, chars_delta, applied = mutation
    return _OverrideApplyResult(
        applied=applied,
        chars_delta=chars_delta,
        curated_value=curated_value if applied else None,
    )


def _sanitize_current_ir(context: _OverrideApplyContext) -> None:
    context.current_ir = sanitize_curated_messages(
        context.current_ir,
        preserve_orphan_tool_results=codex_has_tool_result_only_turn(context.original_ir),
    )


def _build_override_audit(
    *,
    entries: list[OverrideAuditEntry],
    before: tuple[int, int, int],
    after: tuple[int, int, int],
) -> OverrideAudit:
    sys_before, tools_before, msgs_before = before
    sys_after, tools_after, msgs_after = after
    return OverrideAudit(
        entries=entries,
        chars_before=sum(before),
        chars_after=sum(after),
        system_chars_before=sys_before,
        system_chars_after=sys_after,
        tools_chars_before=tools_before,
        tools_chars_after=tools_after,
        messages_chars_before=msgs_before,
        messages_chars_after=msgs_after,
    )
