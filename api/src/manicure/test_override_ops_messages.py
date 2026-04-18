"""Tests for override message and text operations."""

from __future__ import annotations

import pytest

from manicure.ir import (
    InternalRequest,
    Message,
    SystemPart,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from manicure.overrides import Override, apply_overrides, get_store
from manicure.test_override_support import TOOL_BASH, TOOL_READ, make_ir


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    store = get_store()
    store.clear()
    store.enabled = True


class TestToolToggle:
    def test_disable_tool(self) -> None:
        ir = make_ir(tools=[TOOL_BASH, TOOL_READ])
        overrides = [Override(kind="tool_toggle", target="tool:mcp_bash", value=False)]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.tools) == 1
        assert result.tools[0].name == "Read"
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta < 0

    def test_enable_tool_noop(self) -> None:
        ir = make_ir(tools=[TOOL_BASH])
        overrides = [Override(kind="tool_toggle", target="tool:mcp_bash", value=True)]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.tools) == 1
        assert audit.entries[0].chars_delta == 0

    def test_missing_tool_skips_silently(self) -> None:
        ir = make_ir(tools=[TOOL_BASH])
        overrides = [
            Override(kind="tool_toggle", target="tool:nonexistent", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.tools) == 1
        assert audit.entries[0].applied is False


class TestToolDescription:
    def test_rewrite_description(self) -> None:
        ir = make_ir(tools=[TOOL_BASH])
        overrides = [
            Override(
                kind="tool_description",
                target="tool:mcp_bash",
                value="Run commands safely",
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.tools[0].description == "Run commands safely"
        assert audit.entries[0].applied is True

    def test_missing_tool_skips(self) -> None:
        ir = make_ir(tools=[TOOL_BASH])
        overrides = [
            Override(kind="tool_description", target="tool:missing", value="new desc")
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False


class TestSystemPartToggle:
    def test_disable_system_part(self) -> None:
        ir = make_ir(system=[SystemPart(text="part-0"), SystemPart(text="part-1")])
        overrides = [
            Override(kind="system_part_toggle", target="system:0", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 1
        assert result.system[0].text == "part-1"
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta == -len("part-0")

    def test_enable_system_part_noop(self) -> None:
        ir = make_ir(system=[SystemPart(text="part-0")])
        overrides = [Override(kind="system_part_toggle", target="system:0", value=True)]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 1

    def test_out_of_range_skips(self) -> None:
        ir = make_ir(system=[SystemPart(text="only")])
        overrides = [
            Override(kind="system_part_toggle", target="system:5", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 1
        assert audit.entries[0].applied is False


class TestSystemPartText:
    def test_rewrite_text(self) -> None:
        ir = make_ir(system=[SystemPart(text="original text")])
        overrides = [
            Override(
                kind="system_part_text", target="system:0", value="replacement text"
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.system[0].text == "replacement text"
        assert audit.entries[0].applied is True

    def test_out_of_range_skips(self) -> None:
        ir = make_ir(system=[])
        overrides = [Override(kind="system_part_text", target="system:0", value="new")]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False


class TestTruncateToolResult:
    def _ir_with_tool_result(self, text: str = "x" * 5000) -> InternalRequest:
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="tu-1", name="bash", input={"cmd": "ls"})],
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(tool_use_id="tu-1", content=[TextBlock(text=text)])
                ],
            ),
        ]
        return make_ir(messages=messages)

    def test_truncates_long_result(self) -> None:
        ir = self._ir_with_tool_result("a" * 5000)
        overrides = [
            Override(kind="truncate_tool_result", target="toolresult:tu-1", value=100)
        ]
        result, audit = apply_overrides(overrides, ir)

        user_msg = result.messages[1]
        tr_block = user_msg.content[0]
        assert isinstance(tr_block, ToolResultBlock)
        assert len(tr_block.content[0].text) == 100 + len(" [truncated]")  # type: ignore[union-attr]
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta < 0

    def test_short_result_untouched(self) -> None:
        ir = self._ir_with_tool_result("short")
        overrides = [
            Override(kind="truncate_tool_result", target="toolresult:tu-1", value=100)
        ]
        result, _ = apply_overrides(overrides, ir)
        user_msg = result.messages[1]
        tr_block = user_msg.content[0]
        assert isinstance(tr_block, ToolResultBlock)
        assert tr_block.content[0].text == "short"  # type: ignore[union-attr]

    def test_missing_tool_use_id_skips(self) -> None:
        ir = self._ir_with_tool_result()
        overrides = [
            Override(
                kind="truncate_tool_result", target="toolresult:nonexistent", value=100
            )
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False

    def test_zero_value_not_applied(self) -> None:
        ir = self._ir_with_tool_result("a" * 5000)
        overrides = [
            Override(kind="truncate_tool_result", target="toolresult:tu-1", value=0)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        user_msg = result.messages[1]
        tr_block = user_msg.content[0]
        assert isinstance(tr_block, ToolResultBlock)
        assert tr_block.content[0].text == "a" * 5000  # type: ignore[union-attr]

    def test_negative_value_not_applied(self) -> None:
        ir = self._ir_with_tool_result("a" * 5000)
        overrides = [
            Override(kind="truncate_tool_result", target="toolresult:tu-1", value=-1)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        user_msg = result.messages[1]
        tr_block = user_msg.content[0]
        assert isinstance(tr_block, ToolResultBlock)
        assert tr_block.content[0].text == "a" * 5000  # type: ignore[union-attr]


class TestMessageBlockToggle:
    def test_disable_block(self) -> None:
        messages = [
            Message(
                role="user",
                content=[TextBlock(text="keep"), TextBlock(text="drop")],
            ),
        ]
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:1", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].text == "keep"  # type: ignore[union-attr]
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta < 0

    def test_enable_block_is_noop(self) -> None:
        messages = [Message(role="user", content=[TextBlock(text="hello")])]
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=True)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.messages[0].content) == 1
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta == 0

    def test_missing_block_skips(self) -> None:
        ir = make_ir()
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:99", value=False)
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False

    def test_missing_message_skips(self) -> None:
        ir = make_ir()
        overrides = [
            Override(kind="message_block_toggle", target="msg:99:blk:0", value=False)
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False

    def test_multiple_blocks_removed(self) -> None:
        messages = [
            Message(
                role="user",
                content=[
                    TextBlock(text="a"),
                    TextBlock(text="b"),
                    TextBlock(text="c"),
                ],
            ),
        ]
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=False),
            Override(kind="message_block_toggle", target="msg:0:blk:2", value=False),
        ]
        result, _ = apply_overrides(overrides, ir)
        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].text == "b"  # type: ignore[union-attr]


class TestMessageText:
    def test_rewrite_text_block(self) -> None:
        messages = [
            Message(role="user", content=[TextBlock(text="original")]),
            Message(role="assistant", content=[TextBlock(text="response")]),
        ]
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="message_text", target="msg:0:blk:0", value="modified")
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.messages[0].content[0].text == "modified"  # type: ignore[union-attr]
        assert audit.entries[0].applied is True

    def test_out_of_range_msg_skips(self) -> None:
        ir = make_ir()
        overrides = [Override(kind="message_text", target="msg:99:blk:0", value="nope")]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False

    def test_out_of_range_blk_skips(self) -> None:
        ir = make_ir()
        overrides = [Override(kind="message_text", target="msg:0:blk:99", value="nope")]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False

    def test_non_text_block_skips(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="tu-1", name="fn", input={})],
            ),
        ]
        ir = make_ir(messages=messages)
        overrides = [Override(kind="message_text", target="msg:0:blk:0", value="new")]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
