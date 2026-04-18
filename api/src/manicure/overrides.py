"""Override model, store, and apply logic for the Manicure pipeline.

Replaces the rules engine with a direct override model. Users edit
request content in the breakpoint editor; edits produce typed overrides
that persist across exchanges within a session.

This module imports only from ``manicure.ir``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from manicure.override_audit import (
    OverrideAudit,
    OverrideAuditEntry,
    count_chars_parts,
    identity_audit,
)
from manicure.override_ops_messages import (
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
from manicure.override_ops_metadata import (
    apply_provider_extras_set,
    apply_sampling_set,
)
from manicure.override_state import OverrideStore, get_store
from manicure.override_targets import (
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
    from manicure.ir import InternalRequest

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
    chars_before = sys_before + tools_before + msgs_before
    entries: list[OverrideAuditEntry] = []
    sorted_overrides = sorted(overrides, key=lambda o: _PRIORITY[o.kind])

    current_ir = ir

    # Track original indices removed so later overrides can adjust.
    removed_system_indices: set[int] = set()
    removed_blk_indices: dict[int, set[int]] = {}

    for override in sorted_overrides:
        kind = override.kind
        target = override.target
        value = override.value

        applied = False
        chars_delta = 0
        # curated_value rides alongside the audit entry for text-bearing
        # kinds so downstream consumers (the Inspect tab) don't have to
        # replay the pop-cascade to recover what landed where. Stays None
        # for toggles and scalar kinds.
        curated_value: str | None = None

        if kind == "tool_toggle":
            tool_name = parse_tool_name(target)
            if tool_name is not None and isinstance(value, bool):
                if value:
                    applied = any(t.name == tool_name for t in ir.tools)
                else:
                    current_ir, chars_delta, applied = apply_tool_toggle(
                        current_ir, tool_name, value
                    )

        elif kind == "tool_description":
            tool_name = parse_tool_name(target)
            if tool_name is not None and isinstance(value, str):
                current_ir, chars_delta, applied = apply_tool_description(
                    current_ir, tool_name, value
                )
                if applied:
                    curated_value = value

        elif kind == "system_part_toggle":
            original_index = parse_system_index(target)
            if original_index is not None and isinstance(value, bool):
                if value:
                    applied = 0 <= original_index < len(ir.system)
                elif original_index in removed_system_indices:
                    applied = False
                else:
                    adjusted = adjust_system_index(
                        original_index, removed_system_indices
                    )
                    current_ir, chars_delta, applied = apply_system_part_toggle(
                        current_ir, adjusted, value
                    )
                    if applied:
                        removed_system_indices.add(original_index)

        elif kind == "system_part_text":
            original_index = parse_system_index(target)
            if original_index is not None and isinstance(value, str):
                if original_index in removed_system_indices:
                    applied = False
                else:
                    adjusted = adjust_system_index(
                        original_index, removed_system_indices
                    )
                    current_ir, chars_delta, applied = apply_system_part_text(
                        current_ir, adjusted, value
                    )
                    if applied:
                        curated_value = value

        elif kind == "truncate_tool_result":
            tool_use_id = parse_tool_result_id(target)
            if tool_use_id is not None and isinstance(value, int) and value > 0:
                (
                    current_ir,
                    chars_delta,
                    applied,
                    curated_value,
                ) = apply_truncate_tool_result(current_ir, tool_use_id, value)

        elif kind == "message_block_toggle":
            parsed = parse_message_target(target)
            if parsed is not None and isinstance(value, bool):
                msg_idx, original_blk_idx = parsed
                if value:
                    applied = 0 <= msg_idx < len(
                        ir.messages
                    ) and 0 <= original_blk_idx < len(ir.messages[msg_idx].content)
                else:
                    adjusted_blk = adjust_blk_index(
                        msg_idx, original_blk_idx, removed_blk_indices
                    )
                    if adjusted_blk is None:
                        applied = False
                    else:
                        current_ir, chars_delta, applied = apply_message_block_toggle(
                            current_ir, msg_idx, adjusted_blk
                        )
                        if applied:
                            removed_blk_indices.setdefault(msg_idx, set()).add(
                                original_blk_idx
                            )

        elif kind == "message_text":
            parsed = parse_message_target(target)
            if parsed is not None and isinstance(value, str):
                msg_idx, original_blk_idx = parsed
                adjusted_blk = adjust_blk_index(
                    msg_idx, original_blk_idx, removed_blk_indices
                )
                if adjusted_blk is None:
                    applied = False
                else:
                    current_ir, chars_delta, applied = apply_message_text(
                        current_ir, msg_idx, adjusted_blk, value
                    )
                    if applied:
                        curated_value = value

        elif kind == "sampling_set":
            # sampling_set and provider_extras_set both transport their
            # payloads as JSON-encoded strings so floats, lists, and dicts
            # ride on the same narrow Override.value union used by the
            # content-editing kinds. Malformed JSON fails the apply
            # gracefully: the audit entry marks it unapplied and the IR
            # stays unchanged.
            field = parse_sampling_field(target)
            if field is not None and isinstance(value, str):
                try:
                    parsed_value = json.loads(value)
                except json.JSONDecodeError:
                    applied = False
                else:
                    current_ir, chars_delta, applied = apply_sampling_set(
                        current_ir, field, parsed_value
                    )

        elif kind == "provider_extras_set":
            key = parse_provider_extras_key(target)
            if key is not None and isinstance(value, str):
                try:
                    parsed_value = json.loads(value)
                except json.JSONDecodeError:
                    applied = False
                else:
                    current_ir, chars_delta, applied = apply_provider_extras_set(
                        current_ir, key, parsed_value
                    )

        entries.append(
            OverrideAuditEntry(
                kind=kind,
                target=target,
                applied=applied,
                chars_delta=chars_delta,
                curated_value=curated_value,
            )
        )

    # Final cleanup pass: remove empty text blocks and empty messages
    # before the chars_after accounting, so the audit's totals match
    # what actually ships upstream. Audit entries are not amended;
    # sanitization is a derived consequence of the user's overrides,
    # not a user-visible action of its own.
    current_ir = sanitize_curated_messages(
        current_ir,
        preserve_orphan_tool_results=codex_has_tool_result_only_turn(ir),
    )

    sys_after, tools_after, msgs_after = count_chars_parts(current_ir)
    chars_after = sys_after + tools_after + msgs_after
    return current_ir, OverrideAudit(
        entries=entries,
        chars_before=chars_before,
        chars_after=chars_after,
        system_chars_before=sys_before,
        system_chars_after=sys_after,
        tools_chars_before=tools_before,
        tools_chars_after=tools_after,
        messages_chars_before=msgs_before,
        messages_chars_after=msgs_after,
    )
