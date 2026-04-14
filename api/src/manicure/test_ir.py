"""Tests for IR model construction and immutability."""

import pytest
from pydantic import ValidationError

from manicure.ir import (
    ImageBlock,
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ThinkingBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
    UsageStats,
)


class TestContentBlocks:
    def test_text_block(self) -> None:
        b = TextBlock(text="hello")
        assert b.type == "text"
        assert b.text == "hello"

    def test_tool_use_block(self) -> None:
        b = ToolUseBlock(id="t1", name="read", input={"path": "/tmp"})
        assert b.type == "tool_use"
        assert b.name == "read"
        assert b.input == {"path": "/tmp"}

    def test_tool_result_block(self) -> None:
        b = ToolResultBlock(
            tool_use_id="t1",
            content=[TextBlock(text="file contents")],
        )
        assert b.type == "tool_result"
        assert not b.is_error
        assert len(b.content) == 1

    def test_thinking_block(self) -> None:
        b = ThinkingBlock(text="let me think")
        assert b.type == "thinking"
        assert b.provider_data is None

    def test_image_block(self) -> None:
        b = ImageBlock(source={"type": "base64", "data": "abc"})
        assert b.type == "image"

    def test_unknown_block(self) -> None:
        b = UnknownBlock(raw={"type": "custom", "data": 42})
        assert b.type == "unknown"


class TestFrozenEnforcement:
    def test_text_block_is_frozen(self) -> None:
        b = TextBlock(text="hello")
        with pytest.raises(ValidationError):
            b.text = "world"  # type: ignore[misc]

    def test_message_is_frozen(self) -> None:
        m = Message(role="user", content=[TextBlock(text="hi")])
        with pytest.raises(ValidationError):
            m.role = "assistant"  # type: ignore[misc]

    def test_internal_request_is_frozen(self) -> None:
        ir = InternalRequest(
            model="anthropic/claude-opus-4-6",
            provider="anthropic",
            system=[],
            tools=[],
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            sampling=SamplingParams(max_tokens=1024),
            metadata=RequestMetadata(),
        )
        with pytest.raises(ValidationError):
            ir.model = "other"  # type: ignore[misc]


class TestInternalRequest:
    def test_minimal_construction(self) -> None:
        ir = InternalRequest(
            model="anthropic/claude-opus-4-6",
            provider="anthropic",
            system=[],
            tools=[],
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            sampling=SamplingParams(max_tokens=1024),
            metadata=RequestMetadata(),
        )
        assert ir.stream is False
        assert ir.provider_extras == {}

    def test_full_construction(self) -> None:
        ir = InternalRequest(
            model="anthropic/claude-opus-4-6",
            provider="anthropic",
            system=[SystemPart(text="You are helpful")],
            tools=[
                ToolDef(
                    name="read",
                    description="Read a file",
                    input_schema={"type": "object"},
                )
            ],
            messages=[
                Message(role="user", content=[TextBlock(text="hi")]),
            ],
            sampling=SamplingParams(max_tokens=4096, temperature=0.7),
            metadata=RequestMetadata(session_id="s1"),
            stream=True,
            provider_extras={"beta": True},
        )
        assert len(ir.system) == 1
        assert len(ir.tools) == 1
        assert len(ir.messages) == 1
        assert ir.stream is True


class TestInternalResponse:
    def test_construction(self) -> None:
        resp = InternalResponse(
            id="msg_01",
            model="anthropic/claude-opus-4-6",
            provider="anthropic",
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=100, output_tokens=50),
            content=[TextBlock(text="Hello!")],
        )
        assert resp.id == "msg_01"
        assert resp.usage.input_tokens == 100
        assert resp.provider_extras == {}


class TestMessagesValidation:
    def test_empty_messages_raises_validation_error(self) -> None:
        """InternalRequest.messages requires min_length=1."""
        with pytest.raises(ValidationError, match="messages"):
            InternalRequest(
                model="anthropic/claude-opus-4-6",
                provider="anthropic",
                system=[],
                tools=[],
                messages=[],
                sampling=SamplingParams(max_tokens=1024),
                metadata=RequestMetadata(),
            )

    def test_single_message_is_valid(self) -> None:
        ir = InternalRequest(
            model="anthropic/claude-opus-4-6",
            provider="anthropic",
            system=[],
            tools=[],
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            sampling=SamplingParams(max_tokens=1024),
            metadata=RequestMetadata(),
        )
        assert len(ir.messages) == 1


class TestModelSerialization:
    def test_round_trip(self) -> None:
        ir = InternalRequest(
            model="anthropic/claude-opus-4-6",
            provider="anthropic",
            system=[SystemPart(text="system prompt")],
            tools=[],
            messages=[
                Message(role="user", content=[TextBlock(text="hello")]),
            ],
            sampling=SamplingParams(max_tokens=1024),
            metadata=RequestMetadata(),
        )
        dumped = ir.model_dump(mode="json")
        restored = InternalRequest.model_validate(dumped)
        assert restored == ir
