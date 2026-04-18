"""Integration tests for the override apply pipeline."""

from __future__ import annotations

import pytest

from manicure.ir import Message, SystemPart, TextBlock, ToolResultBlock, ToolUseBlock
from manicure.overrides import Override, apply_overrides, get_store
from manicure.test_override_support import TOOL_BASH, make_ir


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    store = get_store()
    store.clear()
    store.enabled = True


class TestPriorityOrdering:
    def test_toggle_before_rewrite_tool(self) -> None:
        """Disabling a tool prevents its description rewrite from applying."""
        ir = make_ir(tools=[TOOL_BASH])
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
        toggle_entry = next(
            entry for entry in audit.entries if entry.kind == "tool_toggle"
        )
        desc_entry = next(
            entry for entry in audit.entries if entry.kind == "tool_description"
        )
        assert toggle_entry.applied is True
        assert desc_entry.applied is False

    def test_toggle_before_rewrite_system(self) -> None:
        """Disabling a system part prevents its text rewrite from applying."""
        ir = make_ir(system=[SystemPart(text="original")])
        overrides = [
            Override(kind="system_part_text", target="system:0", value="rewritten"),
            Override(kind="system_part_toggle", target="system:0", value=False),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 0
        toggle_entry = next(
            entry for entry in audit.entries if entry.kind == "system_part_toggle"
        )
        text_entry = next(
            entry for entry in audit.entries if entry.kind == "system_part_text"
        )
        assert toggle_entry.applied is True
        assert text_entry.applied is False


class TestIndexShifting:
    def test_multiple_system_part_toggles(self) -> None:
        ir = make_ir(
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
        result, _ = apply_overrides(overrides, ir)
        assert len(result.system) == 2
        assert result.system[0].text == "B"
        assert result.system[1].text == "D"

    def test_system_text_after_system_toggle(self) -> None:
        ir = make_ir(
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
        result, _ = apply_overrides(overrides, ir)
        assert len(result.system) == 2
        assert result.system[0].text == "B"
        assert result.system[1].text == "new C"

    def test_system_text_on_removed_index_skips(self) -> None:
        ir = make_ir(system=[SystemPart(text="A"), SystemPart(text="B")])
        overrides = [
            Override(kind="system_part_toggle", target="system:0", value=False),
            Override(kind="system_part_text", target="system:0", value="new A"),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.system) == 1
        assert result.system[0].text == "B"
        text_entry = next(
            entry for entry in audit.entries if entry.kind == "system_part_text"
        )
        assert text_entry.applied is False

    def test_message_text_after_block_toggle(self) -> None:
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
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=False),
            Override(kind="message_text", target="msg:0:blk:2", value="new c"),
        ]
        result, _ = apply_overrides(overrides, ir)
        assert len(result.messages[0].content) == 2
        assert result.messages[0].content[0].text == "b"  # type: ignore[union-attr]
        assert result.messages[0].content[1].text == "new c"  # type: ignore[union-attr]

    def test_message_text_with_multiple_preceding_block_toggles(self) -> None:
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
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=False),
            Override(kind="message_block_toggle", target="msg:0:blk:1", value=False),
            Override(kind="message_text", target="msg:0:blk:3", value="new second"),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.messages[0].content[0].text == "first"  # type: ignore[union-attr]
        assert result.messages[0].content[1].text == "new second"  # type: ignore[union-attr]
        msg_entry = next(
            entry for entry in audit.entries if entry.kind == "message_text"
        )
        assert msg_entry.applied is True


class TestSanitizeCuratedMessages:
    def test_user_message_emptied_by_block_toggle_is_dropped(self) -> None:
        messages = [
            Message(role="user", content=[TextBlock(text="only")]),
            Message(role="assistant", content=[TextBlock(text="reply")]),
        ]
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:0:blk:0", value=False)
        ]
        result, audit = apply_overrides(overrides, ir)
        assert len(result.messages) == 1
        assert result.messages[0].role == "assistant"
        assert audit.chars_after < audit.chars_before

    def test_assistant_message_emptied_by_block_toggle_is_dropped(self) -> None:
        messages = [
            Message(role="user", content=[TextBlock(text="ask")]),
            Message(role="assistant", content=[TextBlock(text="answer")]),
        ]
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:1:blk:0", value=False)
        ]
        result, _ = apply_overrides(overrides, ir)
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"

    def test_empty_text_block_is_dropped_from_message(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[TextBlock(text="keep this"), TextBlock(text="zap me")],
            )
        ]
        ir = make_ir(messages=messages)
        overrides = [Override(kind="message_text", target="msg:0:blk:1", value="")]
        result, _ = apply_overrides(overrides, ir)
        assert len(result.messages) == 1
        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].text == "keep this"  # type: ignore[union-attr]

    def test_message_dropped_when_all_text_blocks_become_empty(self) -> None:
        messages = [
            Message(
                role="user",
                content=[TextBlock(text="a"), TextBlock(text="b")],
            ),
            Message(role="assistant", content=[TextBlock(text="reply")]),
        ]
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="message_text", target="msg:0:blk:0", value=""),
            Override(kind="message_text", target="msg:0:blk:1", value=""),
        ]
        result, _ = apply_overrides(overrides, ir)
        assert len(result.messages) == 1
        assert result.messages[0].role == "assistant"

    def test_non_text_blocks_with_empty_payloads_are_preserved(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="tu-1", name="ping", input={})],
            ),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="tu-1", content=[])],
            ),
        ]
        ir = make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        assert len(result.messages) == 2
        assert len(result.messages[0].content) == 1
        assert len(result.messages[1].content) == 1

    def test_pre_existing_empty_messages_get_cleaned_without_overrides(self) -> None:
        messages = [
            Message(role="user", content=[]),
            Message(role="assistant", content=[TextBlock(text="orphan reply")]),
        ]
        ir = make_ir(messages=messages)
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
        ir = make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        assert len(result.messages) == 1
        assert len(result.messages[0].content) == 1
        assert result.messages[0].content[0].text == "real content"  # type: ignore[union-attr]


class TestOrphanPairPruning:
    def test_orphan_tool_use_is_dropped_when_result_is_toggled_off(self) -> None:
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
        ir = make_ir(messages=messages)
        overrides = [
            Override(kind="message_block_toggle", target="msg:1:blk:0", value=False)
        ]
        result, _ = apply_overrides(overrides, ir)
        assistant = result.messages[0]
        assert len(assistant.content) == 1
        assert assistant.content[0].type == "text"
        user = result.messages[1]
        assert len(user.content) == 1
        assert user.content[0].type == "text"
        assert user.content[0].text == "thanks"

    def test_orphan_tool_result_is_dropped_when_use_is_toggled_off(self) -> None:
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
        ir = make_ir(messages=messages)
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
        ir = make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        assert len(result.messages) == 2
        assert len(result.messages[0].content) == 1
        assert len(result.messages[1].content) == 1

    def test_message_emptied_by_orphan_pruning_is_dropped(self) -> None:
        messages = [
            Message(role="user", content=[TextBlock(text="hi")]),
            Message(role="assistant", content=[TextBlock(text="hello")]),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="never-called", content=[])],
            ),
        ]
        ir = make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        assert len(result.messages) == 2
        assert all(message.content for message in result.messages)

    def test_pre_existing_orphans_are_cleaned_without_overrides(self) -> None:
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
        ir = make_ir(messages=messages)
        result, _ = apply_overrides([], ir)
        assistant_blocks = result.messages[0].content
        assert len(assistant_blocks) == 2
        kept_use_ids = [
            block.id for block in assistant_blocks if isinstance(block, ToolUseBlock)
        ]
        assert kept_use_ids == ["paired"]
        user_blocks = result.messages[1].content
        assert len(user_blocks) == 1
        assert isinstance(user_blocks[0], ToolResultBlock)
        assert user_blocks[0].tool_use_id == "paired"

    def test_codex_tool_result_only_turn_survives_noop_sanitization(self) -> None:
        messages = [
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="call_readme",
                        content=[TextBlock(text="README.md")],
                        provider_data={"type": "function_call_output"},
                    ),
                    ToolResultBlock(
                        tool_use_id="call_pwd",
                        content=[TextBlock(text="/workspace")],
                        provider_data={"type": "function_call_output"},
                    ),
                    ToolResultBlock(
                        tool_use_id="call_workspace",
                        content=[TextBlock(text="workspace/path")],
                        provider_data={"type": "custom_tool_call_output"},
                    ),
                ],
            ),
        ]
        ir = make_ir(messages=messages).model_copy(
            update={"provider": "codex", "model": "codex/gpt-5.4"}
        )

        result, audit = apply_overrides([], ir)

        assert len(result.messages) == 1
        assert len(result.messages[0].content) == 3
        kept_result_ids = [
            block.tool_use_id
            for block in result.messages[0].content
            if isinstance(block, ToolResultBlock)
        ]
        assert kept_result_ids == ["call_readme", "call_pwd", "call_workspace"]
        assert audit.messages_chars_before == audit.messages_chars_after
        assert audit.messages_chars_after > 0
