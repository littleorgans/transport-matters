"""Override model, store, and apply logic for the Manicure pipeline.

Replaces the rules engine with a direct override model. Users edit
request content in the breakpoint editor; edits produce typed overrides
that persist across exchanges within a session.

This module imports only from ``manicure.ir``.
"""

from __future__ import annotations

import copy
import json
from collections import OrderedDict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from manicure.ir import (
    ContentBlock,
    InternalRequest,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

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


# ── Override store ────────────────────────────────────────────────


class OverrideStore:
    """Session-scoped override state. Lives in the addon process."""

    def __init__(self) -> None:
        self._overrides: OrderedDict[tuple[str, str], Override] = OrderedDict()
        self._enabled: bool = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def upsert(self, override: Override) -> None:
        key = (override.kind, override.target)
        if override.value is None:
            self._overrides.pop(key, None)
        else:
            self._overrides[key] = override

    def remove(self, kind: str, target: str) -> bool:
        return self._overrides.pop((kind, target), None) is not None

    def get_all(self) -> list[Override]:
        return list(self._overrides.values())

    def clear(self) -> None:
        self._overrides.clear()


_store = OverrideStore()


def get_store() -> OverrideStore:
    return _store


# ── Audit models ─────────────────────────────────────────────────


class OverrideAuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    target: str
    applied: bool  # False if target was missing
    chars_delta: int  # positive = added, negative = removed


class OverrideAudit(BaseModel):
    entries: list[OverrideAuditEntry]
    chars_before: int
    chars_after: int
    system_chars_before: int = 0
    system_chars_after: int = 0
    tools_chars_before: int = 0
    tools_chars_after: int = 0
    messages_chars_before: int = 0
    messages_chars_after: int = 0

    @property
    def chars_delta(self) -> int:
        return self.chars_after - self.chars_before


# ── Char counting (shared with addon stats) ──────────────────────


def count_chars_parts(ir: InternalRequest) -> tuple[int, int, int]:
    """Return (system_chars, tools_chars, messages_chars) for an IR."""
    system_chars = sum(len(sp.text) for sp in ir.system)
    tools_chars = sum(
        len(t.name) + len(t.description) + len(json.dumps(t.input_schema))
        for t in ir.tools
    )
    messages_chars = 0
    for msg in ir.messages:
        for block in msg.content:
            messages_chars += len(block.model_dump_json())
    return system_chars, tools_chars, messages_chars


def _count_chars(ir: InternalRequest) -> int:
    """Rough character count of the IR payload."""
    return sum(count_chars_parts(ir))


# ── Transform helpers ─────────────────────────────────────────────
#
# Each returns (new_ir, chars_delta, applied). All are pure.


def _apply_tool_toggle(
    ir: InternalRequest, tool_name: str, enabled: bool
) -> tuple[InternalRequest, int, bool]:
    """Toggle a tool on/off by name."""
    if enabled:
        return ir, 0, True

    kept = []
    chars_removed = 0
    found = False
    for tool in ir.tools:
        if tool.name == tool_name:
            found = True
            chars_removed += (
                len(tool.name)
                + len(tool.description)
                + len(json.dumps(tool.input_schema))
            )
        else:
            kept.append(tool)

    if not found:
        return ir, 0, False
    return ir.model_copy(update={"tools": kept}), -chars_removed, True


def _apply_tool_description(
    ir: InternalRequest, tool_name: str, new_desc: str
) -> tuple[InternalRequest, int, bool]:
    """Rewrite a tool's description text."""
    new_tools = []
    delta = 0
    found = False
    for tool in ir.tools:
        if tool.name == tool_name:
            found = True
            delta = len(new_desc) - len(tool.description)
            new_tools.append(tool.model_copy(update={"description": new_desc}))
        else:
            new_tools.append(tool)

    if not found:
        return ir, 0, False
    return ir.model_copy(update={"tools": new_tools}), delta, True


def _apply_system_part_toggle(
    ir: InternalRequest, index: int, enabled: bool
) -> tuple[InternalRequest, int, bool]:
    """Toggle a system part on/off by index."""
    if enabled:
        return ir, 0, True
    if index < 0 or index >= len(ir.system):
        return ir, 0, False

    removed = ir.system[index]
    new_system = list(ir.system)
    new_system.pop(index)
    return ir.model_copy(update={"system": new_system}), -len(removed.text), True


def _apply_system_part_text(
    ir: InternalRequest, index: int, new_text: str
) -> tuple[InternalRequest, int, bool]:
    """Replace a system part's text content."""
    if index < 0 or index >= len(ir.system):
        return ir, 0, False

    old_text = ir.system[index].text
    delta = len(new_text) - len(old_text)
    new_part = ir.system[index].model_copy(update={"text": new_text})
    new_system = list(ir.system)
    new_system[index] = new_part
    return ir.model_copy(update={"system": new_system}), delta, True


def _apply_truncate_tool_result(
    ir: InternalRequest, tool_use_id: str, max_chars: int
) -> tuple[InternalRequest, int, bool]:
    """Truncate a specific tool result by tool_use_id."""
    found = False
    chars_delta = 0
    new_messages: list[Message] = []

    for msg in ir.messages:
        if msg.role != "user":
            new_messages.append(msg)
            continue

        has_target = any(
            isinstance(block, ToolResultBlock) and block.tool_use_id == tool_use_id
            for block in msg.content
        )
        if not has_target:
            new_messages.append(msg)
            continue

        found = True
        new_content: list[ContentBlock] = []
        for block in msg.content:
            if (
                not isinstance(block, ToolResultBlock)
                or block.tool_use_id != tool_use_id
            ):
                new_content.append(block)
                continue

            original_text = "".join(
                tb.text for tb in block.content if isinstance(tb, TextBlock)
            )
            if len(original_text) > max_chars:
                truncated = original_text[:max_chars] + " [truncated]"
                chars_delta += len(truncated) - len(original_text)
                new_block = block.model_copy(
                    update={"content": [TextBlock(type="text", text=truncated)]}
                )
                new_content.append(new_block)
            else:
                new_content.append(block)

        new_messages.append(msg.model_copy(update={"content": new_content}))

    if not found:
        return ir, 0, False
    return ir.model_copy(update={"messages": new_messages}), chars_delta, True


def _apply_message_block_toggle(
    ir: InternalRequest, msg_idx: int, blk_idx: int
) -> tuple[InternalRequest, int, bool]:
    """Remove a content block at the given indices."""
    if msg_idx < 0 or msg_idx >= len(ir.messages):
        return ir, 0, False

    msg = ir.messages[msg_idx]
    if blk_idx < 0 or blk_idx >= len(msg.content):
        return ir, 0, False

    block = msg.content[blk_idx]
    chars_removed = len(block.model_dump_json())
    new_content = list(msg.content)
    new_content.pop(blk_idx)
    new_msg = msg.model_copy(update={"content": new_content})
    new_messages = list(ir.messages)
    new_messages[msg_idx] = new_msg
    return ir.model_copy(update={"messages": new_messages}), -chars_removed, True


_SAMPLING_FIELDS = frozenset(
    {"max_tokens", "temperature", "top_p", "top_k", "stop_sequences"}
)


def _sampling_value_valid(field: str, value: object) -> bool:
    """Shape-check a parsed sampling value against the field's expected type.

    Values arrive JSON-decoded. bool is a subclass of int in Python, so the
    isinstance checks reject True/False for numeric fields explicitly — the
    provider would not treat ``max_tokens=True`` kindly.
    """
    if field == "max_tokens":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 1
    if field in {"temperature", "top_p"}:
        if value is None:
            return True
        if isinstance(value, bool):
            return False
        return isinstance(value, (int, float))
    if field == "top_k":
        if value is None:
            return True
        return isinstance(value, int) and not isinstance(value, bool)
    if field == "stop_sequences":
        return isinstance(value, list) and all(isinstance(s, str) for s in value)
    return False


def _apply_sampling_set(
    ir: InternalRequest, field: str, value: object
) -> tuple[InternalRequest, int, bool]:
    """Set a field on ir.sampling to a parsed value. chars_delta is always 0.

    Sampling knobs are scalar metadata, not content — they don't contribute
    to system/tools/messages char totals, so char accounting stays untouched.
    """
    if field not in _SAMPLING_FIELDS:
        return ir, 0, False
    if not _sampling_value_valid(field, value):
        return ir, 0, False
    new_sampling = ir.sampling.model_copy(update={field: value})
    return ir.model_copy(update={"sampling": new_sampling}), 0, True


def _is_forbidden_segment(segment: str) -> bool:
    """Reject path segments that could enable attribute-style escapes.

    ``constructor`` and Python dunder patterns (``__x__``) are refused so a
    dotted path like ``provider_extras:thinking.__proto__`` cannot land in
    a downstream JSON consumer as prototype-pollution, and cannot navigate
    into Python internal attribute-style slots if the dict ever meets an
    attribute lookup.
    """
    if segment == "constructor":
        return True
    return segment.startswith("__") and segment.endswith("__") and len(segment) >= 4


def _set_nested_path(node: dict[str, Any], path: list[str], value: Any) -> bool:
    """Traverse ``path`` creating empty-dict intermediates as needed, set leaf.

    Refuses to overwrite a non-dict intermediate: if the IR currently has
    e.g. ``thinking = "plain-string"`` and the override wants to set
    ``thinking.display = "summarized"``, the path is malformed for this
    shape and the override should be marked unapplied.
    """
    for seg in path[:-1]:
        if seg not in node:
            node[seg] = {}
        elif not isinstance(node[seg], dict):
            return False
        node = node[seg]
    node[path[-1]] = value
    return True


def _delete_nested_path(root: dict[str, Any], path: list[str]) -> bool:
    """Delete the leaf and recursively prune empty-dict parents.

    Idempotent on missing leaves (clearing a key that isn't there is
    success — the desired state already holds). Rejects only when an
    intermediate exists but isn't a dict, mirroring ``_set_nested_path``.

    The recursive prune means ``provider_extras`` never retains empty-dict
    leftovers at any depth after a clear: if ``output_config.effort`` is
    the only key under ``output_config``, clearing it also removes
    ``output_config`` from ``provider_extras``.
    """
    chain: list[tuple[dict[str, Any], str]] = []
    node = root
    for seg in path[:-1]:
        if seg not in node:
            return True  # nothing to delete; idempotent success
        if not isinstance(node[seg], dict):
            return False  # malformed path for current IR shape
        chain.append((node, seg))
        node = node[seg]
    node.pop(path[-1], None)
    for parent, parent_key in reversed(chain):
        if not parent[parent_key]:
            del parent[parent_key]
    return True


def _apply_provider_extras_set(
    ir: InternalRequest, key: str, value: object
) -> tuple[InternalRequest, int, bool]:
    """Set a (possibly dotted) path in ir.provider_extras to a parsed value.

    A JSON ``null`` deletes the leaf and recursively prunes any empty-dict
    parents up to (but not including) the ``provider_extras`` root — matches
    the adapter convention that absent keys mean "not set" (e.g.,
    ``thinking`` removed == thinking off), and keeps the dict free of empty
    scaffolding at any depth.

    Dotted-path syntax walks nested dicts so ``thinking.display`` targets
    ``provider_extras["thinking"]["display"]``. Segments matching Python
    dunder patterns or equal to ``constructor`` are rejected. Empty
    segments (e.g. trailing or consecutive dots) are rejected.
    """
    if not key:
        return ir, 0, False
    path = key.split(".")
    if any(not seg or _is_forbidden_segment(seg) for seg in path):
        return ir, 0, False

    # Deep-copy so nested dict mutation doesn't leak into the frozen
    # original IR via shared references — shallow copy was safe for the
    # flat-key version but no longer covers us once paths can nest.
    new_extras = copy.deepcopy(dict(ir.provider_extras))

    if value is None:
        if not _delete_nested_path(new_extras, path):
            return ir, 0, False
    else:
        if not _set_nested_path(new_extras, path, value):
            return ir, 0, False

    return ir.model_copy(update={"provider_extras": new_extras}), 0, True


def _apply_message_text(
    ir: InternalRequest, msg_idx: int, blk_idx: int, new_text: str
) -> tuple[InternalRequest, int, bool]:
    """Replace a message text block at the given indices."""
    if msg_idx < 0 or msg_idx >= len(ir.messages):
        return ir, 0, False

    msg = ir.messages[msg_idx]
    if blk_idx < 0 or blk_idx >= len(msg.content):
        return ir, 0, False

    block = msg.content[blk_idx]
    if not isinstance(block, TextBlock):
        return ir, 0, False

    delta = len(new_text) - len(block.text)
    new_block = block.model_copy(update={"text": new_text})
    new_content = list(msg.content)
    new_content[blk_idx] = new_block
    new_msg = msg.model_copy(update={"content": new_content})
    new_messages = list(ir.messages)
    new_messages[msg_idx] = new_msg
    return ir.model_copy(update={"messages": new_messages}), delta, True


# ── Post-pipeline sanitization ───────────────────────────────────


def _sanitize_curated_messages(ir: InternalRequest) -> InternalRequest:
    """Drop empty text blocks, orphaned tool pairs, and empty messages.

    The Anthropic API rejects three states the override pipeline can
    naturally produce:

    1. User messages with ``content: []`` (must have non-empty content)
    2. Text blocks with ``text == ""`` (treated as malformed)
    3. ``tool_use`` without a matching ``tool_result``, or vice versa
       (each tool_result must have a corresponding tool_use)

    The frontend keeps tool_use/tool_result toggles in tandem so a user
    cannot reach state 3 by hand, but the rule belongs here too as
    defense in depth: an upstream payload could already be unbalanced,
    or a future code path could re-introduce orphans.

    Block-level cleanup applies to:

    - ``TextBlock`` with empty text
    - ``ToolUseBlock`` whose id has no matching ``tool_result``
    - ``ToolResultBlock`` whose ``tool_use_id`` has no matching ``tool_use``

    Other block types (``tool_use`` with ``{}`` input, ``tool_result``
    with ``[]`` content) have legitimate empty representations and are
    preserved. Messages whose content goes empty after block cleanup
    are dropped.
    """
    # First pass: collect tool_use ids and tool_result tool_use_ids so
    # we can compute the orphan sets in one shot.
    use_ids: set[str] = set()
    result_ids: set[str] = set()
    for msg in ir.messages:
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                use_ids.add(block.id)
            elif isinstance(block, ToolResultBlock):
                result_ids.add(block.tool_use_id)
    paired = use_ids & result_ids
    orphan_use_ids = use_ids - paired
    orphan_result_ids = result_ids - paired

    # Second pass: drop empty text blocks and orphan tool blocks, then
    # drop messages whose content goes empty as a result.
    cleaned: list[Message] = []
    for msg in ir.messages:
        kept_blocks: list[ContentBlock] = []
        for block in msg.content:
            if isinstance(block, TextBlock) and block.text == "":
                continue
            if isinstance(block, ToolUseBlock) and block.id in orphan_use_ids:
                continue
            if (
                isinstance(block, ToolResultBlock)
                and block.tool_use_id in orphan_result_ids
            ):
                continue
            kept_blocks.append(block)
        if not kept_blocks:
            continue
        cleaned.append(msg.model_copy(update={"content": kept_blocks}))
    return ir.model_copy(update={"messages": cleaned})


# ── Index adjustment helpers ──────────────────────────────────────


def _adjust_system_index(original_index: int, removed_indices: set[int]) -> int:
    """Map an original system index to its current position after removals."""
    return original_index - sum(1 for r in removed_indices if r < original_index)


def _adjust_blk_index(
    msg_idx: int, original_blk_idx: int, removed_blk_indices: dict[int, set[int]]
) -> int | None:
    """Map an original block index to its current position after earlier removals.

    Only ``message_block_toggle`` mutates the block layout during the
    apply pipeline, so the shift map is built up as each toggle runs.
    Returns ``None`` if the target block itself was already removed.
    """
    removed = removed_blk_indices.get(msg_idx, set())
    if original_blk_idx in removed:
        return None
    return original_blk_idx - sum(1 for r in removed if r < original_blk_idx)


def identity_audit(ir: InternalRequest) -> OverrideAudit:
    """Return a zero-delta audit with no entries (used when bypass is on)."""
    sys_c, tools_c, msgs_c = count_chars_parts(ir)
    total = sys_c + tools_c + msgs_c
    return OverrideAudit(
        entries=[],
        chars_before=total,
        chars_after=total,
        system_chars_before=sys_c,
        system_chars_after=sys_c,
        tools_chars_before=tools_c,
        tools_chars_after=tools_c,
        messages_chars_before=msgs_c,
        messages_chars_after=msgs_c,
    )


# ── Target parsing ───────────────────────────────────────────────


def _parse_prefixed(target: str, prefix: str) -> str | None:
    """Extract the value after ``prefix`` if ``target`` starts with it."""
    if target.startswith(prefix):
        return target[len(prefix) :]
    return None


def _parse_prefixed_int(target: str, prefix: str) -> int | None:
    """Extract an integer value after ``prefix``."""
    raw = _parse_prefixed(target, prefix)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_tool_name(target: str) -> str | None:
    """Extract tool name from ``tool:{name}``."""
    return _parse_prefixed(target, "tool:")


def _parse_system_index(target: str) -> int | None:
    """Extract index from ``system:{index}``."""
    return _parse_prefixed_int(target, "system:")


def _parse_tool_result_id(target: str) -> str | None:
    """Extract tool_use_id from ``toolresult:{id}``."""
    return _parse_prefixed(target, "toolresult:")


def _parse_sampling_field(target: str) -> str | None:
    """Extract field name from ``sampling:{field}``."""
    return _parse_prefixed(target, "sampling:")


def _parse_provider_extras_key(target: str) -> str | None:
    """Extract key from ``provider_extras:{key}``."""
    return _parse_prefixed(target, "provider_extras:")


def _parse_message_target(target: str) -> tuple[int, int] | None:
    """Extract (msg_idx, blk_idx) from ``msg:{idx}:blk:{idx}``."""
    parts = target.split(":")
    if len(parts) != 4 or parts[0] != "msg" or parts[2] != "blk":
        return None
    try:
        return int(parts[1]), int(parts[3])
    except ValueError:
        return None


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

        if kind == "tool_toggle":
            tool_name = _parse_tool_name(target)
            if tool_name is not None and isinstance(value, bool):
                if value:
                    applied = any(t.name == tool_name for t in ir.tools)
                else:
                    current_ir, chars_delta, applied = _apply_tool_toggle(
                        current_ir, tool_name, value
                    )

        elif kind == "tool_description":
            tool_name = _parse_tool_name(target)
            if tool_name is not None and isinstance(value, str):
                current_ir, chars_delta, applied = _apply_tool_description(
                    current_ir, tool_name, value
                )

        elif kind == "system_part_toggle":
            original_index = _parse_system_index(target)
            if original_index is not None and isinstance(value, bool):
                if value:
                    applied = 0 <= original_index < len(ir.system)
                elif original_index in removed_system_indices:
                    applied = False
                else:
                    adjusted = _adjust_system_index(
                        original_index, removed_system_indices
                    )
                    current_ir, chars_delta, applied = _apply_system_part_toggle(
                        current_ir, adjusted, value
                    )
                    if applied:
                        removed_system_indices.add(original_index)

        elif kind == "system_part_text":
            original_index = _parse_system_index(target)
            if original_index is not None and isinstance(value, str):
                if original_index in removed_system_indices:
                    applied = False
                else:
                    adjusted = _adjust_system_index(
                        original_index, removed_system_indices
                    )
                    current_ir, chars_delta, applied = _apply_system_part_text(
                        current_ir, adjusted, value
                    )

        elif kind == "truncate_tool_result":
            tool_use_id = _parse_tool_result_id(target)
            if tool_use_id is not None and isinstance(value, int) and value > 0:
                current_ir, chars_delta, applied = _apply_truncate_tool_result(
                    current_ir, tool_use_id, value
                )

        elif kind == "message_block_toggle":
            parsed = _parse_message_target(target)
            if parsed is not None and isinstance(value, bool):
                msg_idx, original_blk_idx = parsed
                if value:
                    applied = 0 <= msg_idx < len(
                        ir.messages
                    ) and 0 <= original_blk_idx < len(ir.messages[msg_idx].content)
                else:
                    adjusted_blk = _adjust_blk_index(
                        msg_idx, original_blk_idx, removed_blk_indices
                    )
                    if adjusted_blk is None:
                        applied = False
                    else:
                        current_ir, chars_delta, applied = _apply_message_block_toggle(
                            current_ir, msg_idx, adjusted_blk
                        )
                        if applied:
                            removed_blk_indices.setdefault(msg_idx, set()).add(
                                original_blk_idx
                            )

        elif kind == "message_text":
            parsed = _parse_message_target(target)
            if parsed is not None and isinstance(value, str):
                msg_idx, original_blk_idx = parsed
                adjusted_blk = _adjust_blk_index(
                    msg_idx, original_blk_idx, removed_blk_indices
                )
                if adjusted_blk is None:
                    applied = False
                else:
                    current_ir, chars_delta, applied = _apply_message_text(
                        current_ir, msg_idx, adjusted_blk, value
                    )

        elif kind == "sampling_set":
            # sampling_set and provider_extras_set both transport their
            # payloads as JSON-encoded strings so floats, lists, and dicts
            # ride on the same narrow Override.value union used by the
            # content-editing kinds. Malformed JSON fails the apply
            # gracefully: the audit entry marks it unapplied and the IR
            # stays unchanged.
            field = _parse_sampling_field(target)
            if field is not None and isinstance(value, str):
                try:
                    parsed_value = json.loads(value)
                except json.JSONDecodeError:
                    applied = False
                else:
                    current_ir, chars_delta, applied = _apply_sampling_set(
                        current_ir, field, parsed_value
                    )

        elif kind == "provider_extras_set":
            key = _parse_provider_extras_key(target)
            if key is not None and isinstance(value, str):
                try:
                    parsed_value = json.loads(value)
                except json.JSONDecodeError:
                    applied = False
                else:
                    current_ir, chars_delta, applied = _apply_provider_extras_set(
                        current_ir, key, parsed_value
                    )

        entries.append(
            OverrideAuditEntry(
                kind=kind,
                target=target,
                applied=applied,
                chars_delta=chars_delta,
            )
        )

    # Final cleanup pass: remove empty text blocks and empty messages
    # before the chars_after accounting, so the audit's totals match
    # what actually ships upstream. Audit entries are not amended;
    # sanitization is a derived consequence of the user's overrides,
    # not a user-visible action of its own.
    current_ir = _sanitize_curated_messages(current_ir)

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
