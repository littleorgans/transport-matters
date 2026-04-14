"""Tests for the override model, store, and apply pipeline."""

from __future__ import annotations

import pytest

from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ThinkingBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
)
from manicure.overrides import (
    Override,
    OverrideStore,
    apply_overrides,
    get_store,
)

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    """Reset the module-level store between tests."""
    store = get_store()
    store.clear()
    store.enabled = True


def _make_ir(
    system: list[SystemPart] | None = None,
    tools: list[ToolDef] | None = None,
    messages: list[Message] | None = None,
) -> InternalRequest:
    return InternalRequest(
        model="claude-3",
        provider="anthropic",
        system=system or [],
        tools=tools or [],
        messages=messages or [Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


_TOOL_BASH = ToolDef(
    name="mcp_bash",
    description="Execute shell commands",
    input_schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
)
_TOOL_READ = ToolDef(
    name="Read",
    description="Read a file from disk",
    input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
)


# ── OverrideStore lifecycle ──────────────────────────────────────


class TestOverrideStore:
    def test_empty_store(self) -> None:
        store = OverrideStore()
        assert store.get_all() == []
        assert store.enabled is True

    def test_upsert_creates(self) -> None:
        store = OverrideStore()
        o = Override(kind="tool_toggle", target="tool:bash", value=False)
        store.upsert(o)
        assert store.get_all() == [o]

    def test_upsert_replaces(self) -> None:
        store = OverrideStore()
        o1 = Override(kind="tool_toggle", target="tool:bash", value=False)
        o2 = Override(kind="tool_toggle", target="tool:bash", value=True)
        store.upsert(o1)
        store.upsert(o2)
        assert len(store.get_all()) == 1
        assert store.get_all()[0].value is True

    def test_upsert_none_removes(self) -> None:
        store = OverrideStore()
        store.upsert(Override(kind="tool_toggle", target="tool:bash", value=False))
        store.upsert(Override(kind="tool_toggle", target="tool:bash", value=None))
        assert store.get_all() == []

    def test_upsert_none_missing_is_noop(self) -> None:
        store = OverrideStore()
        store.upsert(Override(kind="tool_toggle", target="tool:bash", value=None))
        assert store.get_all() == []

    def test_remove(self) -> None:
        store = OverrideStore()
        store.upsert(Override(kind="tool_toggle", target="tool:bash", value=False))
        assert store.remove("tool_toggle", "tool:bash") is True
        assert store.get_all() == []

    def test_remove_missing_returns_false(self) -> None:
        store = OverrideStore()
        assert store.remove("tool_toggle", "tool:nonexistent") is False

    def test_clear(self) -> None:
        store = OverrideStore()
        store.upsert(Override(kind="tool_toggle", target="tool:a", value=False))
        store.upsert(Override(kind="tool_toggle", target="tool:b", value=False))
        store.clear()
        assert store.get_all() == []

    def test_enabled_toggle(self) -> None:
        store = OverrideStore()
        assert store.enabled is True
        store.enabled = False
        assert store.enabled is False
        store.enabled = True
        assert store.enabled is True

    def test_module_singleton(self) -> None:
        """get_store() returns the same instance."""
        assert get_store() is get_store()


# ── tool_toggle ──────────────────────────────────────────────────


class TestToolToggle:
    def test_disable_tool(self) -> None:
        ir = _make_ir(tools=[_TOOL_BASH, _TOOL_READ])
        overrides = [Override(kind="tool_toggle", target="tool:mcp_bash", value=False)]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.tools) == 1
        assert result.tools[0].name == "Read"
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta < 0

    def test_enable_tool_noop(self) -> None:
        ir = _make_ir(tools=[_TOOL_BASH])
        overrides = [Override(kind="tool_toggle", target="tool:mcp_bash", value=True)]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.tools) == 1
        assert audit.entries[0].chars_delta == 0

    def test_missing_tool_skips_silently(self) -> None:
        ir = _make_ir(tools=[_TOOL_BASH])
        overrides = [
            Override(kind="tool_toggle", target="tool:nonexistent", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.tools) == 1
        assert audit.entries[0].applied is False


# ── tool_description ─────────────────────────────────────────────


class TestToolDescription:
    def test_rewrite_description(self) -> None:
        ir = _make_ir(tools=[_TOOL_BASH])
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
        ir = _make_ir(tools=[_TOOL_BASH])
        overrides = [
            Override(kind="tool_description", target="tool:missing", value="new desc")
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False


# ── system_part_toggle ───────────────────────────────────────────


class TestSystemPartToggle:
    def test_disable_system_part(self) -> None:
        ir = _make_ir(system=[SystemPart(text="part-0"), SystemPart(text="part-1")])
        overrides = [
            Override(kind="system_part_toggle", target="system:0", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 1
        assert result.system[0].text == "part-1"
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta == -len("part-0")

    def test_enable_system_part_noop(self) -> None:
        ir = _make_ir(system=[SystemPart(text="part-0")])
        overrides = [Override(kind="system_part_toggle", target="system:0", value=True)]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 1

    def test_out_of_range_skips(self) -> None:
        ir = _make_ir(system=[SystemPart(text="only")])
        overrides = [
            Override(kind="system_part_toggle", target="system:5", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 1
        assert audit.entries[0].applied is False


# ── system_part_text ─────────────────────────────────────────────


class TestSystemPartText:
    def test_rewrite_text(self) -> None:
        ir = _make_ir(system=[SystemPart(text="original text")])
        overrides = [
            Override(
                kind="system_part_text", target="system:0", value="replacement text"
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.system[0].text == "replacement text"
        assert audit.entries[0].applied is True

    def test_out_of_range_skips(self) -> None:
        ir = _make_ir(system=[])
        overrides = [Override(kind="system_part_text", target="system:0", value="new")]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False


# ── strip_thinking ───────────────────────────────────────────────


class TestStripThinking:
    def test_removes_thinking_blocks(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[
                    ThinkingBlock(text="let me think..."),
                    TextBlock(text="here is my answer"),
                ],
            )
        ]
        ir = _make_ir(messages=messages)
        overrides = [Override(kind="strip_thinking", target="global", value=True)]
        result, audit = apply_overrides(overrides, ir)

        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].type == "text"
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta < 0

    def test_false_value_is_noop(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[ThinkingBlock(text="thought"), TextBlock(text="answer")],
            )
        ]
        ir = _make_ir(messages=messages)
        overrides = [Override(kind="strip_thinking", target="global", value=False)]
        result, audit = apply_overrides(overrides, ir)

        assert len(result.messages[0].content) == 2
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta == 0

    def test_no_thinking_blocks_is_noop(self) -> None:
        ir = _make_ir()
        overrides = [Override(kind="strip_thinking", target="global", value=True)]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta == 0


# ── truncate_tool_result ─────────────────────────────────────────


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
        return _make_ir(messages=messages)

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
        result, audit = apply_overrides(overrides, ir)
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
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False

    def test_zero_value_not_applied(self) -> None:
        """truncate_tool_result requires value > 0; zero is rejected."""
        ir = self._ir_with_tool_result("a" * 5000)
        overrides = [
            Override(kind="truncate_tool_result", target="toolresult:tu-1", value=0)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        # Original content unchanged
        user_msg = result.messages[1]
        tr_block = user_msg.content[0]
        assert isinstance(tr_block, ToolResultBlock)
        assert tr_block.content[0].text == "a" * 5000  # type: ignore[union-attr]

    def test_negative_value_not_applied(self) -> None:
        """truncate_tool_result requires value > 0; negative is rejected."""
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


# ── message_block_toggle ─────────────────────────────────────────


class TestMessageBlockToggle:
    def test_disable_block(self) -> None:
        messages = [
            Message(
                role="user",
                content=[TextBlock(text="keep"), TextBlock(text="drop")],
            ),
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:1", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].text == "keep"  # type: ignore[union-attr]
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta < 0

    def test_enable_block_is_noop(self) -> None:
        messages = [
            Message(role="user", content=[TextBlock(text="hello")]),
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=True)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.messages[0].content) == 1
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta == 0

    def test_missing_block_skips(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:99", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False

    def test_missing_message_skips(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(kind="message_block_toggle", target="msg:99:blk:0", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
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
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=False),
            Override(kind="message_block_toggle", target="msg:0:blk:2", value=False),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].text == "b"  # type: ignore[union-attr]


# ── message_text ─────────────────────────────────────────────────


class TestMessageText:
    def test_rewrite_text_block(self) -> None:
        messages = [
            Message(role="user", content=[TextBlock(text="original")]),
            Message(role="assistant", content=[TextBlock(text="response")]),
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_text", target="msg:0:blk:0", value="modified")
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.messages[0].content[0].text == "modified"  # type: ignore[union-attr]
        assert audit.entries[0].applied is True

    def test_out_of_range_msg_skips(self) -> None:
        ir = _make_ir()
        overrides = [Override(kind="message_text", target="msg:99:blk:0", value="nope")]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False

    def test_out_of_range_blk_skips(self) -> None:
        ir = _make_ir()
        overrides = [Override(kind="message_text", target="msg:0:blk:99", value="nope")]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False

    def test_non_text_block_skips(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="tu-1", name="fn", input={})],
            ),
        ]
        ir = _make_ir(messages=messages)
        overrides = [Override(kind="message_text", target="msg:0:blk:0", value="new")]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False


# ── Priority ordering ────────────────────────────────────────────


class TestPriorityOrdering:
    def test_toggle_before_rewrite_tool(self) -> None:
        """Disabling a tool prevents its description rewrite from applying."""
        ir = _make_ir(tools=[_TOOL_BASH])
        overrides = [
            Override(
                kind="tool_description",
                target="tool:mcp_bash",
                value="new desc",
            ),
            Override(kind="tool_toggle", target="tool:mcp_bash", value=False),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.tools) == 0
        # tool_toggle should be applied, tool_description should not find target
        toggle_entry = next(e for e in audit.entries if e.kind == "tool_toggle")
        desc_entry = next(e for e in audit.entries if e.kind == "tool_description")
        assert toggle_entry.applied is True
        assert desc_entry.applied is False

    def test_toggle_before_rewrite_system(self) -> None:
        """Disabling a system part prevents its text rewrite from applying."""
        ir = _make_ir(system=[SystemPart(text="original")])
        overrides = [
            Override(kind="system_part_text", target="system:0", value="rewritten"),
            Override(kind="system_part_toggle", target="system:0", value=False),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 0
        toggle_entry = next(e for e in audit.entries if e.kind == "system_part_toggle")
        text_entry = next(e for e in audit.entries if e.kind == "system_part_text")
        assert toggle_entry.applied is True
        assert text_entry.applied is False

    def test_strip_thinking_fires_first(self) -> None:
        """strip_thinking runs before any other override."""
        messages = [
            Message(
                role="assistant",
                content=[ThinkingBlock(text="thought"), TextBlock(text="answer")],
            )
        ]
        ir = _make_ir(tools=[_TOOL_BASH], messages=messages)
        overrides = [
            Override(kind="tool_toggle", target="tool:mcp_bash", value=False),
            Override(kind="strip_thinking", target="global", value=True),
        ]
        result, audit = apply_overrides(overrides, ir)
        # Both should apply
        assert len(result.tools) == 0
        assert len(result.messages[0].content) == 1
        # strip_thinking is first in the audit entries
        assert audit.entries[0].kind == "strip_thinking"
        assert audit.entries[1].kind == "tool_toggle"


# ── Index shifting ───────────────────────────────────────────────


class TestIndexShifting:
    def test_multiple_system_part_toggles(self) -> None:
        """Removing parts at index 0 and 2 removes the correct original parts."""
        ir = _make_ir(
            system=[
                SystemPart(text="A"),
                SystemPart(text="B"),
                SystemPart(text="C"),
                SystemPart(text="D"),
            ]
        )
        overrides = [
            Override(kind="system_part_toggle", target="system:0", value=False),
            Override(kind="system_part_toggle", target="system:2", value=False),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 2
        assert result.system[0].text == "B"
        assert result.system[1].text == "D"

    def test_system_text_after_system_toggle(self) -> None:
        """system_part_text targets the correct part after toggle removes a lower index."""
        ir = _make_ir(
            system=[
                SystemPart(text="A"),
                SystemPart(text="B"),
                SystemPart(text="C"),
            ]
        )
        overrides = [
            Override(kind="system_part_toggle", target="system:0", value=False),
            Override(kind="system_part_text", target="system:2", value="new C"),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 2
        assert result.system[0].text == "B"
        assert result.system[1].text == "new C"

    def test_system_text_on_removed_index_skips(self) -> None:
        """system_part_text targeting a removed system part is not applied."""
        ir = _make_ir(system=[SystemPart(text="A"), SystemPart(text="B")])
        overrides = [
            Override(kind="system_part_toggle", target="system:0", value=False),
            Override(kind="system_part_text", target="system:0", value="new A"),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 1
        assert result.system[0].text == "B"
        text_entry = next(e for e in audit.entries if e.kind == "system_part_text")
        assert text_entry.applied is False

    def test_message_text_after_strip_thinking(self) -> None:
        """message_text targets the correct block after strip_thinking removes blocks."""
        messages = [
            Message(
                role="assistant",
                content=[
                    ThinkingBlock(text="thought"),
                    TextBlock(text="answer"),
                ],
            )
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="strip_thinking", target="global", value=True),
            Override(kind="message_text", target="msg:0:blk:1", value="new answer"),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].text == "new answer"  # type: ignore[union-attr]

    def test_message_text_on_removed_thinking_block_skips(self) -> None:
        """message_text targeting a removed thinking block is not applied."""
        messages = [
            Message(
                role="assistant",
                content=[
                    ThinkingBlock(text="thought"),
                    TextBlock(text="answer"),
                ],
            )
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="strip_thinking", target="global", value=True),
            Override(kind="message_text", target="msg:0:blk:0", value="nope"),
        ]
        result, audit = apply_overrides(overrides, ir)
        msg_entry = next(e for e in audit.entries if e.kind == "message_text")
        assert msg_entry.applied is False

    def test_block_toggle_after_strip_thinking(self) -> None:
        """message_block_toggle targets the correct block after strip_thinking."""
        messages = [
            Message(
                role="assistant",
                content=[
                    ThinkingBlock(text="thought"),
                    TextBlock(text="keep"),
                    TextBlock(text="drop"),
                ],
            )
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="strip_thinking", target="global", value=True),
            Override(kind="message_block_toggle", target="msg:0:blk:2", value=False),
        ]
        result, audit = apply_overrides(overrides, ir)
        # ThinkingBlock removed by strip_thinking, then original blk:2 ("drop") removed
        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].text == "keep"  # type: ignore[union-attr]

    def test_block_toggle_on_removed_thinking_skips(self) -> None:
        """message_block_toggle targeting a removed thinking block is not applied."""
        messages = [
            Message(
                role="assistant",
                content=[ThinkingBlock(text="t"), TextBlock(text="a")],
            )
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="strip_thinking", target="global", value=True),
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=False),
        ]
        result, audit = apply_overrides(overrides, ir)
        toggle_entry = next(
            e for e in audit.entries if e.kind == "message_block_toggle"
        )
        assert toggle_entry.applied is False

    def test_message_text_after_block_toggle(self) -> None:
        """message_text adjusts indices after message_block_toggle removes a block."""
        messages = [
            Message(
                role="user",
                content=[
                    TextBlock(text="a"),
                    TextBlock(text="b"),
                    TextBlock(text="c"),
                ],
            )
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=False),
            Override(kind="message_text", target="msg:0:blk:2", value="new c"),
        ]
        result, audit = apply_overrides(overrides, ir)
        # blk:0 removed, blk:2 ("c") shifts to position 1
        assert len(result.messages[0].content) == 2
        assert result.messages[0].content[0].text == "b"  # type: ignore[union-attr]
        assert result.messages[0].content[1].text == "new c"  # type: ignore[union-attr]

    def test_message_text_with_multiple_thinking_blocks(self) -> None:
        """Block indices adjust correctly when multiple thinking blocks precede the target."""
        messages = [
            Message(
                role="assistant",
                content=[
                    ThinkingBlock(text="t1"),
                    ThinkingBlock(text="t2"),
                    TextBlock(text="first"),
                    TextBlock(text="second"),
                ],
            )
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="strip_thinking", target="global", value=True),
            Override(kind="message_text", target="msg:0:blk:3", value="new second"),
        ]
        result, audit = apply_overrides(overrides, ir)
        # Original blk:3 was TextBlock("second"), now at position 1
        assert result.messages[0].content[0].text == "first"  # type: ignore[union-attr]
        assert result.messages[0].content[1].text == "new second"  # type: ignore[union-attr]
        msg_entry = next(e for e in audit.entries if e.kind == "message_text")
        assert msg_entry.applied is True


# ── Audit aggregate ──────────────────────────────────────────────


class TestAuditAggregate:
    def test_chars_before_after(self) -> None:
        ir = _make_ir(tools=[_TOOL_BASH, _TOOL_READ])
        overrides = [Override(kind="tool_toggle", target="tool:mcp_bash", value=False)]
        _, audit = apply_overrides(overrides, ir)
        assert audit.chars_before > audit.chars_after
        assert audit.chars_delta < 0

    def test_no_overrides_identity(self) -> None:
        ir = _make_ir()
        result, audit = apply_overrides([], ir)
        assert result == ir
        assert audit.entries == []
        assert audit.chars_before == audit.chars_after
        assert audit.chars_delta == 0
