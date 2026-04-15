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

    def test_message_text_with_multiple_preceding_block_toggles(self) -> None:
        """Block indices adjust correctly when multiple earlier toggles shift the target left."""
        messages = [
            Message(
                role="assistant",
                content=[
                    TextBlock(text="drop1"),
                    TextBlock(text="drop2"),
                    TextBlock(text="first"),
                    TextBlock(text="second"),
                ],
            )
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=False),
            Override(kind="message_block_toggle", target="msg:0:blk:1", value=False),
            Override(kind="message_text", target="msg:0:blk:3", value="new second"),
        ]
        result, audit = apply_overrides(overrides, ir)
        # Original blk:3 was TextBlock("second"), now at position 1 after
        # blk:0 and blk:1 were removed.
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


# ── Curated-message sanitization ─────────────────────────────────


class TestSanitizeCuratedMessages:
    """Anthropic rejects empty-content messages and empty text blocks.

    These tests cover the post-pipeline cleanup that strips both
    states from the curated IR before the audit's chars_after is
    computed and before the IR ships upstream.
    """

    def test_user_message_emptied_by_block_toggle_is_dropped(self) -> None:
        # Single-block user message, last block toggled off → message
        # should not appear in the curated IR.
        messages = [
            Message(role="user", content=[TextBlock(text="only")]),
            Message(role="assistant", content=[TextBlock(text="reply")]),
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.messages) == 1
        assert result.messages[0].role == "assistant"
        # chars_after must reflect the dropped message wrapper, not
        # just the dropped block.
        assert audit.chars_after < audit.chars_before

    def test_assistant_message_emptied_by_block_toggle_is_dropped(self) -> None:
        # Symmetric to the user case; the cleanup rule is role-neutral.
        messages = [
            Message(role="user", content=[TextBlock(text="ask")]),
            Message(role="assistant", content=[TextBlock(text="answer")]),
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:1:blk:0", value=False)
        ]
        result, _ = apply_overrides(overrides, ir)
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"

    def test_empty_text_block_is_dropped_from_message(self) -> None:
        # message_text rewrites the second block to "" → that block
        # should disappear, but the message survives because the
        # first block still carries text.
        messages = [
            Message(
                role="assistant",
                content=[TextBlock(text="keep this"), TextBlock(text="zap me")],
            )
        ]
        ir = _make_ir(messages=messages)
        overrides = [Override(kind="message_text", target="msg:0:blk:1", value="")]
        result, _ = apply_overrides(overrides, ir)
        assert len(result.messages) == 1
        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].text == "keep this"  # type: ignore[union-attr]

    def test_message_dropped_when_all_text_blocks_become_empty(self) -> None:
        # Two-block user message; both blocks rewritten to "". The
        # block-level cleanup zeros the content array, then the
        # message-level cleanup drops the message entirely.
        messages = [
            Message(
                role="user",
                content=[TextBlock(text="a"), TextBlock(text="b")],
            ),
            Message(role="assistant", content=[TextBlock(text="reply")]),
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_text", target="msg:0:blk:0", value=""),
            Override(kind="message_text", target="msg:0:blk:1", value=""),
        ]
        result, _ = apply_overrides(overrides, ir)
        assert len(result.messages) == 1
        assert result.messages[0].role == "assistant"

    def test_non_text_blocks_with_empty_payloads_are_preserved(self) -> None:
        # tool_use with `{}` input is a legitimate no-arg call;
        # tool_result with `[]` content is a legitimate empty result.
        # Sanitization must not touch them.
        messages = [
            Message(
                role="assistant",
                content=[
                    ToolUseBlock(id="tu-1", name="ping", input={}),
                ],
            ),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="tu-1", content=[])],
            ),
        ]
        ir = _make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        assert len(result.messages) == 2
        assert len(result.messages[0].content) == 1
        assert len(result.messages[1].content) == 1

    def test_pre_existing_empty_messages_get_cleaned_without_overrides(self) -> None:
        # Defense in depth: even if upstream somehow hands the editor
        # an IR that already contains an empty message, the cleanup
        # pass strips it on the way back out.
        messages = [
            Message(role="user", content=[]),
            Message(role="assistant", content=[TextBlock(text="orphan reply")]),
        ]
        ir = _make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        assert len(result.messages) == 1
        assert result.messages[0].role == "assistant"

    def test_pre_existing_empty_text_block_gets_cleaned_without_overrides(self) -> None:
        messages = [
            Message(
                role="user",
                content=[TextBlock(text=""), TextBlock(text="real content")],
            ),
        ]
        ir = _make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        assert len(result.messages) == 1
        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].text == "real content"  # type: ignore[union-attr]


# ── Orphan tool_use / tool_result pruning ────────────────────────


class TestOrphanPairPruning:
    """Anthropic requires every tool_result.tool_use_id to match a
    tool_use.id earlier in the conversation. The override pipeline can
    produce orphans on either side (toggle off the call but not the
    result, or vice versa); the curated IR must drop the orphan half so
    the upstream payload is balanced. The frontend keeps these toggles
    in tandem so the orphan state is unreachable by hand, but this
    backend pass is defense in depth.
    """

    def test_orphan_tool_use_is_dropped_when_result_is_toggled_off(self) -> None:
        # Assistant call + matching user result, then the user toggles
        # the result block off. The tool_use becomes an orphan and must
        # be stripped or Anthropic rejects the next turn.
        messages = [
            Message(
                role="assistant",
                content=[
                    TextBlock(text="running it"),
                    ToolUseBlock(id="tu-1", name="bash", input={"cmd": "ls"}),
                ],
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(tool_use_id="tu-1", content=[TextBlock(text="ok")]),
                    TextBlock(text="thanks"),
                ],
            ),
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:1:blk:0", value=False)
        ]
        result, _ = apply_overrides(overrides, ir)
        # Assistant message: orphaned tool_use dropped, text remains
        assistant = result.messages[0]
        assert len(assistant.content) == 1
        assert assistant.content[0].type == "text"
        # User message: tool_result removed by the override, text remains
        user = result.messages[1]
        assert len(user.content) == 1
        assert user.content[0].type == "text"
        assert user.content[0].text == "thanks"

    def test_orphan_tool_result_is_dropped_when_use_is_toggled_off(self) -> None:
        # Symmetric: toggle off the tool_use and the user-side result
        # is left dangling; sanitize must remove it.
        messages = [
            Message(
                role="assistant",
                content=[
                    TextBlock(text="ok"),
                    ToolUseBlock(id="tu-1", name="bash", input={"cmd": "ls"}),
                ],
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(tool_use_id="tu-1", content=[TextBlock(text="ok")]),
                    TextBlock(text="thanks"),
                ],
            ),
        ]
        ir = _make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:1", value=False)
        ]
        result, _ = apply_overrides(overrides, ir)
        assistant = result.messages[0]
        assert len(assistant.content) == 1
        assert assistant.content[0].type == "text"
        user = result.messages[1]
        assert len(user.content) == 1
        assert user.content[0].type == "text"
        assert user.content[0].text == "thanks"

    def test_paired_tool_blocks_survive(self) -> None:
        # Both halves present → neither side is touched.
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="tu-1", name="bash", input={"cmd": "ls"})],
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(tool_use_id="tu-1", content=[TextBlock(text="ok")])
                ],
            ),
        ]
        ir = _make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        assert len(result.messages) == 2
        assert len(result.messages[0].content) == 1
        assert len(result.messages[1].content) == 1

    def test_message_emptied_by_orphan_pruning_is_dropped(self) -> None:
        # The user message holds only an orphaned tool_result. After
        # block-level pruning the message body goes empty, so the
        # message itself is dropped by the same pass.
        messages = [
            Message(role="user", content=[TextBlock(text="hi")]),
            Message(role="assistant", content=[TextBlock(text="hello")]),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="never-called", content=[])],
            ),
        ]
        ir = _make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        assert len(result.messages) == 2
        assert all(m.content for m in result.messages)

    def test_pre_existing_orphans_are_cleaned_without_overrides(self) -> None:
        # Mixed payload entering the editor already unbalanced: one
        # orphan tool_use, one orphan tool_result, one paired pair.
        # Only the paired pair survives.
        messages = [
            Message(
                role="assistant",
                content=[
                    ToolUseBlock(id="orphan-1", name="bash", input={}),
                    ToolUseBlock(id="paired", name="bash", input={}),
                    TextBlock(text="ok"),
                ],
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(tool_use_id="paired", content=[]),
                    ToolResultBlock(tool_use_id="orphan-2", content=[]),
                ],
            ),
        ]
        ir = _make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        # Assistant: orphan tool_use dropped, paired + text remain
        assistant_blocks = result.messages[0].content
        assert len(assistant_blocks) == 2
        kept_use_ids = [b.id for b in assistant_blocks if isinstance(b, ToolUseBlock)]
        assert kept_use_ids == ["paired"]
        # User: orphan tool_result dropped, paired remains
        user_blocks = result.messages[1].content
        assert len(user_blocks) == 1
        assert isinstance(user_blocks[0], ToolResultBlock)
        assert user_blocks[0].tool_use_id == "paired"


# ── Sampling / provider_extras overrides ─────────────────────────


class TestSamplingSet:
    """``sampling_set`` updates the sampling subtree of the IR via JSON-encoded
    values. Chars delta is always 0 since sampling does not contribute to
    system/tools/messages char totals.
    """

    def test_sets_max_tokens(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:max_tokens", value="4096")
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.sampling.max_tokens == 4096
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta == 0

    def test_sets_temperature_float(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:temperature", value="0.7")
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.sampling.temperature == 0.7

    def test_sets_temperature_null_unsets_field(self) -> None:
        # JSON literal "null" is the escape hatch for "unset this field".
        # Contrast with override-level value=None, which removes the
        # override from the store entirely.
        ir = _make_ir().model_copy(
            update={
                "sampling": SamplingParams(max_tokens=1024, temperature=0.9),
            }
        )
        overrides = [
            Override(kind="sampling_set", target="sampling:temperature", value="null")
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.sampling.temperature is None

    def test_sets_top_p_float(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:top_p", value="0.95")
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.sampling.top_p == 0.95

    def test_sets_top_k_int(self) -> None:
        ir = _make_ir()
        overrides = [Override(kind="sampling_set", target="sampling:top_k", value="40")]
        result, _ = apply_overrides(overrides, ir)
        assert result.sampling.top_k == 40

    def test_sets_stop_sequences_list(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(
                kind="sampling_set",
                target="sampling:stop_sequences",
                value='["END", "STOP"]',
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.sampling.stop_sequences == ["END", "STOP"]

    def test_unknown_field_is_unapplied(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:nonsense", value="1")
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.sampling == ir.sampling

    def test_malformed_json_is_unapplied(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(
                kind="sampling_set", target="sampling:temperature", value="not-json"
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.sampling == ir.sampling

    def test_wrong_type_for_field_is_unapplied(self) -> None:
        # max_tokens expects int; a JSON-encoded string must be rejected.
        ir = _make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:max_tokens", value='"four"')
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.sampling == ir.sampling

    def test_max_tokens_rejects_bool(self) -> None:
        # Python's ``True`` is a subclass of int but would be nonsense for
        # max_tokens; the validator rejects it explicitly.
        ir = _make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:max_tokens", value="true")
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.sampling == ir.sampling

    def test_chars_accounting_is_untouched(self) -> None:
        # Sampling edits should not register as content changes in the
        # chars_before/after totals — those track system/tools/messages only.
        ir = _make_ir(
            system=[SystemPart(type="text", text="hello")],
        )
        overrides = [
            Override(kind="sampling_set", target="sampling:max_tokens", value="2048")
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.chars_before == audit.chars_after


class TestProviderExtrasSet:
    """``provider_extras_set`` merges a key/value into the provider_extras
    dict. JSON null deletes the key so adapters that treat absent keys as
    "off" (e.g. Anthropic thinking) can be toggled cleanly.
    """

    def test_sets_thinking_dict(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value='{"type": "enabled", "budget_tokens": 10000}',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.provider_extras["thinking"] == {
            "type": "enabled",
            "budget_tokens": 10000,
        }
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta == 0

    def test_null_value_deletes_key(self) -> None:
        ir = _make_ir().model_copy(
            update={"provider_extras": {"thinking": {"type": "enabled"}}}
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value="null",
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert "thinking" not in result.provider_extras

    def test_merges_alongside_existing_keys(self) -> None:
        ir = _make_ir().model_copy(update={"provider_extras": {"foo": "bar"}})
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value='{"type": "enabled"}',
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras["foo"] == "bar"
        assert result.provider_extras["thinking"] == {"type": "enabled"}

    def test_malformed_json_is_unapplied(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value="{not-json",
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == ir.provider_extras

    def test_empty_key_is_unapplied(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:",
                value='"x"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == ir.provider_extras

    def test_batch_with_sampling_thinking_toggle(self) -> None:
        # Realistic batch: user enables thinking, which both sets the
        # provider_extra and unsets temperature/top_k/top_p. Tests that
        # both kinds can coexist in a single apply and land in order.
        ir = _make_ir().model_copy(
            update={
                "sampling": SamplingParams(
                    max_tokens=1024, temperature=0.7, top_p=0.9, top_k=40
                ),
            }
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value='{"type": "enabled", "budget_tokens": 10000}',
            ),
            Override(kind="sampling_set", target="sampling:temperature", value="null"),
            Override(kind="sampling_set", target="sampling:top_p", value="null"),
            Override(kind="sampling_set", target="sampling:top_k", value="null"),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.sampling.temperature is None
        assert result.sampling.top_p is None
        assert result.sampling.top_k is None
        assert result.provider_extras["thinking"] == {
            "type": "enabled",
            "budget_tokens": 10000,
        }
        assert all(e.applied for e in audit.entries)


class TestProviderExtrasNestedPath:
    """Dotted-path targets let overrides reach into nested provider_extras
    keys (``thinking.display``, ``output_config.effort``). On clear, empty
    parent dicts prune recursively so the dict carries no empty scaffolding
    at any depth.
    """

    def test_sets_nested_value(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value='"summarized"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.provider_extras == {"thinking": {"display": "summarized"}}
        assert audit.entries[0].applied is True

    def test_sets_nested_preserves_siblings(self) -> None:
        # Setting one nested key must not clobber sibling keys under the
        # same parent — that would defeat the whole point of partial edits.
        ir = _make_ir().model_copy(
            update={
                "provider_extras": {
                    "thinking": {"type": "enabled", "budget_tokens": 8000},
                }
            }
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value='"summarized"',
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras["thinking"] == {
            "type": "enabled",
            "budget_tokens": 8000,
            "display": "summarized",
        }

    def test_sets_deep_path_creates_intermediates(self) -> None:
        # ``output_config.effort`` with no pre-existing output_config key
        # should materialize the intermediate dict automatically.
        ir = _make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:output_config.effort",
                value='"high"',
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras == {"output_config": {"effort": "high"}}

    def test_nested_clear_prunes_empty_parent(self) -> None:
        # When the cleared leaf was the only key under its parent, the
        # empty parent is removed — no ``{"output_config": {}}`` detritus.
        ir = _make_ir().model_copy(
            update={"provider_extras": {"output_config": {"effort": "low"}}}
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:output_config.effort",
                value="null",
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras == {}

    def test_nested_clear_preserves_parent_with_siblings(self) -> None:
        ir = _make_ir().model_copy(
            update={
                "provider_extras": {
                    "thinking": {"type": "enabled", "display": "summarized"},
                }
            }
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value="null",
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras == {"thinking": {"type": "enabled"}}

    def test_nested_clear_recursive_cascade(self) -> None:
        # 3-level nesting: clearing the innermost leaf when it's the sole
        # tenant of both parents collapses the entire chain.
        ir = _make_ir().model_copy(update={"provider_extras": {"a": {"b": {"c": 1}}}})
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:a.b.c",
                value="null",
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras == {}

    def test_nested_clear_cascade_stops_at_sibling(self) -> None:
        # Pruning walks up only while each parent becomes empty. A
        # sibling key anywhere in the chain halts the cascade.
        ir = _make_ir().model_copy(
            update={"provider_extras": {"a": {"b": {"c": 1}, "d": 2}}}
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:a.b.c",
                value="null",
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras == {"a": {"d": 2}}

    def test_nested_clear_on_missing_path_is_idempotent(self) -> None:
        # Clearing a key that isn't there: already in desired state.
        # applied=True so the audit reads "the user's intent succeeded".
        ir = _make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value="null",
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.provider_extras == {}
        assert audit.entries[0].applied is True

    def test_rejects_dunder_segment(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.__proto__",
                value='"x"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == ir.provider_extras

    def test_rejects_constructor_segment(self) -> None:
        ir = _make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:output_config.constructor",
                value='"x"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == ir.provider_extras

    def test_rejects_empty_segment(self) -> None:
        # ``a..b`` splits to ["a", "", "b"]. Empty segments indicate a
        # malformed target; don't paper over it by skipping.
        ir = _make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking..display",
                value='"x"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == ir.provider_extras

    def test_rejects_non_dict_intermediate_on_set(self) -> None:
        # ``thinking`` is a string, so ``thinking.display`` can't be reached
        # without clobbering. Reject rather than silently overwrite.
        ir = _make_ir().model_copy(update={"provider_extras": {"thinking": "plain"}})
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value='"summarized"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == {"thinking": "plain"}

    def test_rejects_non_dict_intermediate_on_clear(self) -> None:
        ir = _make_ir().model_copy(update={"provider_extras": {"thinking": "plain"}})
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value="null",
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == {"thinking": "plain"}

    def test_nested_does_not_mutate_original_ir(self) -> None:
        # With nested paths the shallow-copy approach would share inner
        # dicts by reference; ensure the IR stays pristine after apply.
        ir = _make_ir().model_copy(
            update={"provider_extras": {"thinking": {"type": "enabled"}}}
        )
        original_thinking = ir.provider_extras["thinking"]
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value='"summarized"',
            )
        ]
        _, _ = apply_overrides(overrides, ir)
        assert ir.provider_extras["thinking"] == {"type": "enabled"}
        assert ir.provider_extras["thinking"] is original_thinking
