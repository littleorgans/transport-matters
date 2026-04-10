"""Pipeline engine: applies matching rules to an InternalRequest.

Imports from ``manicure.rules`` and ``manicure.ir``.
``RuleAuditEntry`` is defined in ``manicure.storage.base`` and
re-used here to avoid duplication.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any  # Any: action params

from pydantic import BaseModel

if TYPE_CHECKING:
    from manicure.ir import InternalRequest

from manicure.rules import (
    Rule,
    matches_scope,
    rewrite_tool_description,
    strip_system_part,
    strip_thinking,
    strip_tools,
    truncate_system_part,
    truncate_tool_result,
)
from manicure.storage.base import RuleAuditEntry


class PipelineAudit(BaseModel):
    rules_applied: list[RuleAuditEntry]
    chars_before: int
    chars_after: int

    @property
    def chars_delta(self) -> int:
        return self.chars_after - self.chars_before

    @property
    def tokens_approx(self) -> int:
        return abs(self.chars_delta) // 4


def _count_chars(ir: InternalRequest) -> int:
    """Rough character count of the IR payload."""
    system_chars = sum(len(sp.text) for sp in ir.system)
    tools_chars = sum(
        len(t.name) + len(t.description) + len(json.dumps(t.input_schema))
        for t in ir.tools
    )
    messages_chars = 0
    for msg in ir.messages:
        for block in msg.content:
            messages_chars += len(block.model_dump_json())
    return system_chars + tools_chars + messages_chars


_DISPATCH: dict[
    str,
    type[None] | None,
] = None  # type: ignore[assignment]  # populated lazily to satisfy type checkers


def _get_dispatch() -> dict[str, Any]:  # Any: callable dispatch table
    """Build the action dispatch table."""
    return {
        "strip_tools": strip_tools,
        "strip_thinking": strip_thinking,
        "strip_system_part": strip_system_part,
        "truncate_system_part": truncate_system_part,
        "truncate_tool_result": truncate_tool_result,
        "rewrite_tool_description": rewrite_tool_description,
    }


def _dispatch(
    action: str,
    ir: InternalRequest,
    params: dict[str, Any],  # Any: action params vary by action type
) -> tuple[InternalRequest, dict[str, int]]:
    """Dispatch to the correct action implementation."""
    table = _get_dispatch()
    fn = table.get(action)
    if fn is None:
        return ir, {}
    result: tuple[InternalRequest, dict[str, int]] = fn(ir, params)
    return result


def apply(
    rules: list[Rule], ir: InternalRequest
) -> tuple[InternalRequest, PipelineAudit]:
    """Apply all matching enabled rules in created_at order. Return new IR + audit."""
    chars_before = _count_chars(ir)
    applied: list[RuleAuditEntry] = []

    eligible = sorted(
        [r for r in rules if r.enabled and matches_scope(r, ir)],
        key=lambda r: r.created_at,
    )

    current_ir = ir
    for rule in eligible:
        current_ir, removed = _dispatch(rule.action, current_ir, rule.params)
        applied.append(
            RuleAuditEntry(
                id=rule.id, name=rule.name, action=rule.action, removed=removed
            )
        )

    chars_after = _count_chars(current_ir)
    return current_ir, PipelineAudit(
        rules_applied=applied,
        chars_before=chars_before,
        chars_after=chars_after,
    )
