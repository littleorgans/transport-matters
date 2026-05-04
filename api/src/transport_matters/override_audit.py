"""Private audit models and char accounting helpers for overrides."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from transport_matters.ir import InternalRequest


class OverrideAuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    target: str
    applied: bool
    chars_delta: int
    curated_value: str | None = None


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


def count_chars_parts(ir: InternalRequest) -> tuple[int, int, int]:
    """Return (system_chars, tools_chars, messages_chars) for an IR."""
    system_chars = sum(len(part.text) for part in ir.system)
    tools_chars = sum(
        len(tool.name) + len(tool.description) + len(json.dumps(tool.input_schema))
        for tool in ir.tools
    )
    messages_chars = 0
    for message in ir.messages:
        for block in message.content:
            messages_chars += len(block.model_dump_json())
    return system_chars, tools_chars, messages_chars


def identity_audit(ir: InternalRequest) -> OverrideAudit:
    """Return a zero-delta audit with no entries."""
    system_chars, tools_chars, messages_chars = count_chars_parts(ir)
    total = system_chars + tools_chars + messages_chars
    return OverrideAudit(
        entries=[],
        chars_before=total,
        chars_after=total,
        system_chars_before=system_chars,
        system_chars_after=system_chars,
        tools_chars_before=tools_chars,
        tools_chars_after=tools_chars,
        messages_chars_before=messages_chars,
        messages_chars_after=messages_chars,
    )
