"""Rule model and action implementations for the Manicure pipeline.

Rules define scoped transformations applied to an InternalRequest before
it is forwarded to the provider. Each action is a pure function that
returns a new IR and an audit dict.

This module imports only from ``manicure.ir``.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Literal  # Any: action params vary by action type
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from manicure.ir import (
    ContentBlock,
    InternalRequest,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
)

ActionLiteral = Literal[
    "strip_tools",
    "strip_thinking",
    "strip_system_part",
    "truncate_system_part",
    "truncate_tool_result",
    "rewrite_tool_description",
]


class RuleScope(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    global_: bool = Field(False, alias="global")
    session_id: str | None = None
    device_id: str | None = None
    account_id: str | None = None
    model: str | None = None


class Rule(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    id: str = Field(default_factory=lambda: f"rule_{uuid4().hex[:12]}")
    name: str
    enabled: bool = True
    scope: RuleScope
    action: ActionLiteral
    params: dict[str, Any]  # Any: action params vary by action type
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    applied_count: int = 0


class RuleAuditEntry(BaseModel):
    """Immutable record of a single rule applied during a pipeline run."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    action: str
    removed: dict[str, int]  # int: always integers (tools, chars, blocks)


# ── Scope matching ─────────────────────────────────────────────────


def matches_scope(rule: Rule, ir: InternalRequest) -> bool:
    """Return True if this rule's scope applies to this request."""
    scope = rule.scope
    if scope.global_:
        return True
    matched_any = False
    if scope.session_id is not None:
        if ir.metadata.session_id != scope.session_id:
            return False
        matched_any = True
    if scope.device_id is not None:
        if ir.metadata.device_id != scope.device_id:
            return False
        matched_any = True
    if scope.account_id is not None:
        if ir.metadata.account_id != scope.account_id:
            return False
        matched_any = True
    if scope.model is not None:
        if ir.model != scope.model:
            return False
        matched_any = True
    return matched_any


# ── Action implementations ─────────────────────────────────────────
#
# Each returns (new_ir, audit_dict).  All are deterministic & idempotent.


def strip_tools(
    ir: InternalRequest,
    params: dict[str, Any],  # Any: action params
) -> tuple[InternalRequest, dict[str, int]]:
    """Remove tools matching name / prefix / regex predicates."""
    name = params.get("name")
    prefix = params.get("prefix")
    pattern = params.get("regex")

    def _matches(tool_name: str) -> bool:
        if name is not None and tool_name == name:
            return True
        if prefix is not None and tool_name.startswith(prefix):
            return True
        return pattern is not None and bool(re.search(pattern, tool_name))

    kept = []
    removed_chars = 0
    removed_count = 0
    for tool in ir.tools:
        if _matches(tool.name):
            removed_count += 1
            removed_chars += (
                len(tool.name)
                + len(tool.description)
                + len(json.dumps(tool.input_schema))
            )
        else:
            kept.append(tool)

    new_ir = ir.model_copy(update={"tools": kept})
    return new_ir, {"tools": removed_count, "chars": removed_chars}


def strip_thinking(
    ir: InternalRequest,
    params: dict[str, Any],  # Any: ignored
) -> tuple[InternalRequest, dict[str, int]]:
    """Remove all ThinkingBlock entries from every message."""
    blocks_removed = 0
    chars_removed = 0
    new_messages: list[Message] = []

    for msg in ir.messages:
        new_content = []
        for block in msg.content:
            if isinstance(block, ThinkingBlock):
                blocks_removed += 1
                chars_removed += len(block.text)
            else:
                new_content.append(block)
        new_messages.append(msg.model_copy(update={"content": new_content}))

    new_ir = ir.model_copy(update={"messages": new_messages})
    return new_ir, {"blocks": blocks_removed, "chars": chars_removed}


def strip_system_part(
    ir: InternalRequest,
    params: dict[str, Any],  # Any: action params
) -> tuple[InternalRequest, dict[str, int]]:
    """Remove ir.system[index]. No-op if index out of range."""
    index: int = params.get("index", -1)
    if index < 0 or index >= len(ir.system):
        return ir, {"parts": 0, "chars": 0}

    removed_part = ir.system[index]
    new_system = list(ir.system)
    new_system.pop(index)
    new_ir = ir.model_copy(update={"system": new_system})
    return new_ir, {"parts": 1, "chars": len(removed_part.text)}


def truncate_system_part(
    ir: InternalRequest,
    params: dict[str, Any],  # Any: action params
) -> tuple[InternalRequest, dict[str, int]]:
    """Truncate ir.system[index].text to max_chars if it exceeds the limit."""
    index: int = params.get("index", -1)
    max_chars: int = params.get("max_chars", 0)
    if index < 0 or index >= len(ir.system):
        return ir, {"chars": 0}

    part = ir.system[index]
    if len(part.text) <= max_chars:
        return ir, {"chars": 0}

    original_len = len(part.text)
    truncated_text = part.text[:max_chars] + " [truncated]"
    new_part = part.model_copy(update={"text": truncated_text})
    new_system = list(ir.system)
    new_system[index] = new_part
    new_ir = ir.model_copy(update={"system": new_system})
    chars_removed = original_len - len(truncated_text)
    return new_ir, {"chars": chars_removed}


def truncate_tool_result(
    ir: InternalRequest,
    params: dict[str, Any],  # Any: action params
) -> tuple[InternalRequest, dict[str, int]]:
    """Truncate old or oversized ToolResultBlock content."""
    older_than_turns: int | None = params.get("older_than_turns")
    max_chars: int | None = params.get("max_chars")

    total_messages = len(ir.messages)
    turn_index = 0
    blocks_truncated = 0
    chars_removed = 0
    new_messages: list[Message] = []

    for msg in ir.messages:
        if msg.role == "user":
            turn_index += 1

        needs_rewrite = False
        if msg.role == "user":
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    should_truncate = False
                    effective_max = max_chars

                    if older_than_turns is not None and turn_index <= (
                        total_messages - older_than_turns
                    ):
                        should_truncate = True
                        if effective_max is None:
                            effective_max = 2000

                    if effective_max is not None:
                        content_chars = sum(
                            len(tb.text)
                            for tb in block.content
                            if isinstance(tb, TextBlock)
                        )
                        if content_chars > effective_max:
                            should_truncate = True

                    if should_truncate:
                        needs_rewrite = True
                        break

        if not needs_rewrite:
            new_messages.append(msg)
            continue

        effective_max_for_msg = max_chars
        new_content: list[ContentBlock] = []
        for block in msg.content:
            if not isinstance(block, ToolResultBlock):
                new_content.append(block)
                continue

            should_truncate = False
            local_max = effective_max_for_msg

            if older_than_turns is not None and turn_index <= (
                total_messages - older_than_turns
            ):
                should_truncate = True
                if local_max is None:
                    local_max = 2000

            original_text = "".join(
                tb.text for tb in block.content if isinstance(tb, TextBlock)
            )

            if local_max is not None and len(original_text) > local_max:
                should_truncate = True

            if (
                should_truncate
                and local_max is not None
                and len(original_text) > local_max
            ):
                truncated = original_text[:local_max] + " [truncated]"
                chars_removed += len(original_text) - len(truncated)
                blocks_truncated += 1
                new_block = block.model_copy(
                    update={"content": [TextBlock(type="text", text=truncated)]}
                )
                new_content.append(new_block)
            else:
                new_content.append(block)

        new_messages.append(msg.model_copy(update={"content": new_content}))

    new_ir = ir.model_copy(update={"messages": new_messages})
    return new_ir, {"blocks": blocks_truncated, "chars": chars_removed}


def rewrite_tool_description(
    ir: InternalRequest,
    params: dict[str, Any],  # Any: action params
) -> tuple[InternalRequest, dict[str, int]]:
    """Replace the description of a named tool."""
    target_name: str = params.get("name", "")
    new_desc: str = params.get("new", "")

    new_tools = []
    delta = 0
    found = False
    for tool in ir.tools:
        if tool.name == target_name:
            old_len = len(tool.description)
            new_len = len(new_desc)
            delta = new_len - old_len
            new_tools.append(tool.model_copy(update={"description": new_desc}))
            found = True
        else:
            new_tools.append(tool)

    if not found:
        return ir, {"chars": 0}

    new_ir = ir.model_copy(update={"tools": new_tools})
    return new_ir, {"chars": delta}
