"""Override model, store, and apply logic for the Manicure pipeline.

Replaces the rules engine with a direct override model. Users edit
request content in the breakpoint editor; edits produce typed overrides
that persist across exchanges within a session.

This module imports only from ``manicure.ir``.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Literal

from pydantic import BaseModel, ConfigDict

from manicure.ir import (
    ContentBlock,
    InternalRequest,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
)

# ── Override types ────────────────────────────────────────────────

OverrideKind = Literal[
    "tool_toggle",
    "tool_description",
    "system_part_toggle",
    "system_part_text",
    "message_block_toggle",
    "message_text",
    "strip_thinking",
    "truncate_tool_result",
]

# Fixed priority order: toggles before rewrites, global before targeted.
_PRIORITY: dict[str, int] = {
    "strip_thinking": 0,
    "tool_toggle": 1,
    "tool_description": 2,
    "system_part_toggle": 3,
    "system_part_text": 4,
    "truncate_tool_result": 5,
    "message_block_toggle": 6,
    "message_text": 7,
}


class Override(BaseModel):
    """Single user override. Frozen after creation; replaced on update."""

    model_config = ConfigDict(frozen=True)

    kind: OverrideKind
    target: str
    value: str | bool | int | None
    # bool   -> toggles (tool_toggle, system_part_toggle, message_block_toggle, strip_thinking)
    # str    -> rewrites (tool_description, system_part_text, message_text)
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


def _apply_strip_thinking(
    ir: InternalRequest,
) -> tuple[InternalRequest, int, dict[int, set[int]]]:
    """Remove all ThinkingBlock entries from every message.

    Returns (new_ir, chars_delta, removed_block_indices_per_message).
    The third element maps message index to the set of original block
    indices that were ThinkingBlocks, enabling downstream overrides
    (``message_text``) to adjust their target indices.
    """
    chars_removed = 0
    removed_indices: dict[int, set[int]] = {}
    new_messages: list[Message] = []
    for msg_idx, msg in enumerate(ir.messages):
        new_content: list[ContentBlock] = []
        msg_removed: set[int] = set()
        for blk_idx, block in enumerate(msg.content):
            if isinstance(block, ThinkingBlock):
                chars_removed += len(block.text)
                msg_removed.add(blk_idx)
            else:
                new_content.append(block)
        if msg_removed:
            removed_indices[msg_idx] = msg_removed
        new_messages.append(msg.model_copy(update={"content": new_content}))
    return (
        ir.model_copy(update={"messages": new_messages}),
        -chars_removed,
        removed_indices,
    )


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


# ── Index adjustment helpers ──────────────────────────────────────


def _adjust_system_index(original_index: int, removed_indices: set[int]) -> int:
    """Map an original system index to its current position after removals."""
    return original_index - sum(1 for r in removed_indices if r < original_index)


def _adjust_blk_index(
    msg_idx: int, original_blk_idx: int, removed_blk_indices: dict[int, set[int]]
) -> int | None:
    """Map an original block index to its current position after strip_thinking.

    Returns None if the block itself was removed.
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
    (``system_part_toggle``, ``strip_thinking``), later overrides have their
    target indices adjusted so they still hit the intended item.
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

        if kind == "strip_thinking":
            if isinstance(value, bool) and value:
                current_ir, chars_delta, removed_blk_indices = _apply_strip_thinking(
                    current_ir
                )
            applied = True

        elif kind == "tool_toggle":
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

        entries.append(
            OverrideAuditEntry(
                kind=kind,
                target=target,
                applied=applied,
                chars_delta=chars_delta,
            )
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
