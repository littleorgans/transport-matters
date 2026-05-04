"""Private content mutation helpers for overrides."""

from __future__ import annotations

import json

from transport_matters.ir import (
    ContentBlock,
    InternalRequest,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def codex_has_tool_result_only_turn(ir: InternalRequest) -> bool:
    """Return True for Codex requests that carry tool outputs without tool uses."""
    if ir.provider != "codex":
        return False

    has_tool_use = False
    has_tool_result = False
    for message in ir.messages:
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                has_tool_use = True
            elif isinstance(block, ToolResultBlock):
                has_tool_result = True

    return has_tool_result and not has_tool_use


def count_chars(ir: InternalRequest) -> int:
    """Rough character count of the IR payload."""
    return (
        sum(len(part.text) for part in ir.system)
        + sum(
            len(tool.name) + len(tool.description) + len(json.dumps(tool.input_schema))
            for tool in ir.tools
        )
        + sum(
            len(block.model_dump_json())
            for message in ir.messages
            for block in message.content
        )
    )


def apply_tool_toggle(
    ir: InternalRequest, tool_name: str, enabled: bool
) -> tuple[InternalRequest, int, bool]:
    """Toggle a tool on or off by name."""
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


def apply_tool_description(
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


def apply_system_part_toggle(
    ir: InternalRequest, index: int, enabled: bool
) -> tuple[InternalRequest, int, bool]:
    """Toggle a system part on or off by index."""
    if enabled:
        return ir, 0, True
    if index < 0 or index >= len(ir.system):
        return ir, 0, False

    removed = ir.system[index]
    new_system = list(ir.system)
    new_system.pop(index)
    return ir.model_copy(update={"system": new_system}), -len(removed.text), True


def apply_system_part_text(
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


def apply_truncate_tool_result(
    ir: InternalRequest, tool_use_id: str, max_chars: int
) -> tuple[InternalRequest, int, bool, str | None]:
    """Truncate a specific tool result by tool_use_id."""
    found = False
    chars_delta = 0
    curated_text: str | None = None
    new_messages: list[Message] = []

    for message in ir.messages:
        if message.role != "user":
            new_messages.append(message)
            continue

        has_target = any(
            isinstance(block, ToolResultBlock) and block.tool_use_id == tool_use_id
            for block in message.content
        )
        if not has_target:
            new_messages.append(message)
            continue

        found = True
        new_content: list[ContentBlock] = []
        for block in message.content:
            if (
                not isinstance(block, ToolResultBlock)
                or block.tool_use_id != tool_use_id
            ):
                new_content.append(block)
                continue

            original_text = "".join(
                text_block.text
                for text_block in block.content
                if isinstance(text_block, TextBlock)
            )
            if len(original_text) > max_chars:
                truncated = original_text[:max_chars] + " [truncated]"
                chars_delta += len(truncated) - len(original_text)
                curated_text = truncated
                new_block = block.model_copy(
                    update={"content": [TextBlock(type="text", text=truncated)]}
                )
                new_content.append(new_block)
            else:
                curated_text = original_text
                new_content.append(block)

        new_messages.append(message.model_copy(update={"content": new_content}))

    if not found:
        return ir, 0, False, None
    return (
        ir.model_copy(update={"messages": new_messages}),
        chars_delta,
        True,
        curated_text,
    )


def apply_message_block_toggle(
    ir: InternalRequest, msg_idx: int, blk_idx: int
) -> tuple[InternalRequest, int, bool]:
    """Remove a content block at the given indices."""
    if msg_idx < 0 or msg_idx >= len(ir.messages):
        return ir, 0, False

    message = ir.messages[msg_idx]
    if blk_idx < 0 or blk_idx >= len(message.content):
        return ir, 0, False

    block = message.content[blk_idx]
    chars_removed = len(block.model_dump_json())
    new_content = list(message.content)
    new_content.pop(blk_idx)
    new_message = message.model_copy(update={"content": new_content})
    new_messages = list(ir.messages)
    new_messages[msg_idx] = new_message
    return ir.model_copy(update={"messages": new_messages}), -chars_removed, True


def apply_message_text(
    ir: InternalRequest, msg_idx: int, blk_idx: int, new_text: str
) -> tuple[InternalRequest, int, bool]:
    """Replace a message text block at the given indices."""
    if msg_idx < 0 or msg_idx >= len(ir.messages):
        return ir, 0, False

    message = ir.messages[msg_idx]
    if blk_idx < 0 or blk_idx >= len(message.content):
        return ir, 0, False

    block = message.content[blk_idx]
    if not isinstance(block, TextBlock):
        return ir, 0, False

    delta = len(new_text) - len(block.text)
    new_block = block.model_copy(update={"text": new_text})
    new_content = list(message.content)
    new_content[blk_idx] = new_block
    new_message = message.model_copy(update={"content": new_content})
    new_messages = list(ir.messages)
    new_messages[msg_idx] = new_message
    return ir.model_copy(update={"messages": new_messages}), delta, True


def sanitize_curated_messages(
    ir: InternalRequest,
    *,
    preserve_orphan_tool_results: bool = False,
) -> InternalRequest:
    """Drop empty text blocks, orphaned tool pairs, and empty messages."""
    use_ids: set[str] = set()
    result_ids: set[str] = set()
    for message in ir.messages:
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                use_ids.add(block.id)
            elif isinstance(block, ToolResultBlock):
                result_ids.add(block.tool_use_id)
    paired = use_ids & result_ids
    orphan_use_ids = use_ids - paired
    orphan_result_ids = set() if preserve_orphan_tool_results else (result_ids - paired)

    cleaned: list[Message] = []
    for message in ir.messages:
        kept_blocks: list[ContentBlock] = []
        for block in message.content:
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
        cleaned.append(message.model_copy(update={"content": kept_blocks}))
    return ir.model_copy(update={"messages": cleaned})
