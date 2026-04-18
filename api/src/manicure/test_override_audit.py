"""Tests for override audit behavior."""

from __future__ import annotations

import pytest

from manicure.ir import Message, SystemPart, TextBlock, ToolResultBlock, ToolUseBlock
from manicure.overrides import Override, apply_overrides, get_store
from manicure.test_override_support import TOOL_BASH, TOOL_READ, make_ir


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    store = get_store()
    store.clear()
    store.enabled = True


class TestAuditAggregate:
    def test_chars_before_after(self) -> None:
        ir = make_ir(tools=[TOOL_BASH, TOOL_READ])
        overrides = [Override(kind="tool_toggle", target="tool:mcp_bash", value=False)]
        _, audit = apply_overrides(overrides, ir)
        assert audit.chars_before > audit.chars_after
        assert audit.chars_delta < 0

    def test_no_overrides_identity(self) -> None:
        ir = make_ir()
        result, audit = apply_overrides([], ir)
        assert result == ir
        assert audit.entries == []
        assert audit.chars_before == audit.chars_after


class TestAuditCuratedValue:
    """Audit tracks the curated text for text-bearing override kinds."""

    def test_system_part_text_populates(self) -> None:
        ir = make_ir(system=[SystemPart(text="part-0")])
        overrides = [
            Override(kind="system_part_text", target="system:0", value="rewritten")
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].curated_value == "rewritten"

    def test_tool_description_populates(self) -> None:
        ir = make_ir(tools=[TOOL_BASH])
        overrides = [
            Override(
                kind="tool_description",
                target="tool:mcp_bash",
                value="Run commands safely",
            )
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].curated_value == "Run commands safely"

    def test_message_text_populates(self) -> None:
        messages = [Message(role="user", content=[TextBlock(text="hi")])]
        ir = make_ir(messages=messages)
        overrides = [Override(kind="message_text", target="msg:0:blk:0", value="hello")]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].curated_value == "hello"

    def test_truncate_tool_result_populates_with_truncated_text(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="tu-1", name="bash", input={})],
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="tu-1", content=[TextBlock(text="a" * 500)]
                    )
                ],
            ),
        ]
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="truncate_tool_result", target="toolresult:tu-1", value=100)
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].curated_value == "a" * 100 + " [truncated]"

    def test_truncate_tool_result_short_text_untouched(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="tu-1", name="bash", input={})],
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="tu-1", content=[TextBlock(text="tiny")]
                    )
                ],
            ),
        ]
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="truncate_tool_result", target="toolresult:tu-1", value=100)
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].curated_value == "tiny"

    def test_toggle_kinds_leave_curated_value_none(self) -> None:
        messages = [
            Message(role="user", content=[TextBlock(text="a"), TextBlock(text="b")])
        ]
        ir = make_ir(
            system=[SystemPart(text="sys")],
            tools=[TOOL_BASH],
            messages=messages,
        ).model_copy(update={"provider_extras": {}})
        overrides = [
            Override(kind="tool_toggle", target="tool:mcp_bash", value=False),
            Override(kind="system_part_toggle", target="system:0", value=False),
            Override(kind="message_block_toggle", target="msg:0:blk:1", value=False),
            Override(kind="sampling_set", target="sampling:max_tokens", value="42"),
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value='"on"',
            ),
        ]
        _, audit = apply_overrides(overrides, ir)
        for entry in audit.entries:
            assert entry.applied is True, f"{entry.kind} {entry.target}"
            assert entry.curated_value is None, f"{entry.kind} {entry.target}"

    def test_unapplied_text_override_leaves_curated_value_none(self) -> None:
        ir = make_ir(messages=[Message(role="user", content=[TextBlock(text="hi")])])
        overrides = [Override(kind="message_text", target="msg:0:blk:99", value="nope")]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert audit.entries[0].curated_value is None

    def test_unapplied_truncate_leaves_curated_value_none(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="truncate_tool_result", target="toolresult:missing", value=100
            )
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert audit.entries[0].curated_value is None
