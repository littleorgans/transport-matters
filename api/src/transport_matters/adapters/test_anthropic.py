"""Round-trip tests for the Anthropic adapter.

Each test builds a realistic Anthropic request body, runs it through
``inbound_request`` then ``outbound_request``, and asserts lossless
round-trip (modulo key ordering and whitespace).
"""

import json
from typing import Any

import pytest

from transport_matters.adapters.anthropic import AnthropicAdapter
from transport_matters.ir import ToolResultBlock


@pytest.fixture
def adapter() -> AnthropicAdapter:
    return AnthropicAdapter()


# ── fixtures: raw request bodies ────────────────────────────────────

MINIMAL_REQUEST: dict[str, Any] = {
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}],
    "model": "claude-sonnet-4-20250514",
}

WITH_TOOLS_REQUEST: dict[str, Any] = {
    "max_tokens": 4096,
    "messages": [{"role": "user", "content": [{"type": "text", "text": "Read /tmp/foo"}]}],
    "model": "claude-sonnet-4-20250514",
    "tools": [
        {
            "name": "read_file",
            "description": "Read a file from disk",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
    ],
}

WITH_SYSTEM_CACHE_REQUEST: dict[str, Any] = {
    "max_tokens": 2048,
    "messages": [{"role": "user", "content": [{"type": "text", "text": "Summarise"}]}],
    "model": "claude-sonnet-4-20250514",
    "system": [
        {
            "type": "text",
            "text": "You are a helpful assistant.",
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": "Always be concise.",
        },
    ],
}

WITH_THINKING_REQUEST: dict[str, Any] = {
    "max_tokens": 8192,
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": "Think hard"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "thinking",
                    "thinking": "Let me consider...",
                    "signature": "abc123",
                },
                {"type": "text", "text": "Here is my answer."},
            ],
        },
        {"role": "user", "content": [{"type": "text", "text": "Continue"}]},
    ],
    "model": "claude-sonnet-4-20250514",
    "temperature": 1.0,
}

WITH_METADATA_REQUEST: dict[str, Any] = {
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
    "metadata": {
        "user_id": json.dumps(
            {
                "session_id": "sess-001",
                "device_id": "dev-abc",
                "account_id": "acct-xyz",
            }
        ),
    },
    "model": "claude-sonnet-4-20250514",
}

WITH_TOOL_RESULT_REQUEST: dict[str, Any] = {
    "max_tokens": 4096,
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": "Read /tmp/x"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu_01",
                    "name": "read_file",
                    "input": {"path": "/tmp/x"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_01",
                    "content": [{"type": "text", "text": "file contents here"}],
                }
            ],
        },
    ],
    "model": "claude-sonnet-4-20250514",
}

WITH_EXTRAS_REQUEST: dict[str, Any] = {
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
    "model": "claude-sonnet-4-20250514",
    "stream": True,
    "top_k": 40,
    "top_p": 0.9,
}

# Unknown sibling fields on modeled blocks and on the message object. Each must
# survive the round-trip so an edit elsewhere in the request never drops them.
WITH_BLOCK_EXTRAS_REQUEST: dict[str, Any] = {
    "max_tokens": 1024,
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "look",
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "iVBOR",
                    },
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "custom_message_field": "keep-me",
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "read",
                    "input": {"p": "/x"},
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
    ],
    "model": "claude-sonnet-4-20250514",
}

# tool_result block-level extras, sub-block extras, and an unknown sub-block
# type that must be preserved verbatim instead of stringified.
WITH_TOOL_RESULT_EXTRAS_REQUEST: dict[str, Any] = {
    "max_tokens": 1024,
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_1",
                    "content": [
                        {
                            "type": "text",
                            "text": "ok",
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "document",
                            "source": {"type": "url", "url": "http://x"},
                            "title": "doc",
                        },
                    ],
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    ],
    "model": "claude-sonnet-4-20250514",
}


# ── round-trip tests ───────────────────────────────────────────────


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    """Re-serialize via sorted keys to allow comparison."""
    result: dict[str, Any] = json.loads(json.dumps(data, sort_keys=True))
    return result


class TestRoundTrip:
    def test_minimal(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(MINIMAL_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        result = adapter.outbound_request(ir)
        assert json.loads(result) == _normalise(MINIMAL_REQUEST)

    def test_with_tools(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(WITH_TOOLS_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        result = adapter.outbound_request(ir)
        assert json.loads(result) == _normalise(WITH_TOOLS_REQUEST)

    def test_with_system_cache(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(WITH_SYSTEM_CACHE_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        result = adapter.outbound_request(ir)
        assert json.loads(result) == _normalise(WITH_SYSTEM_CACHE_REQUEST)

    def test_with_thinking(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(WITH_THINKING_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        result = adapter.outbound_request(ir)
        assert json.loads(result) == _normalise(WITH_THINKING_REQUEST)

    def test_with_tool_result(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(WITH_TOOL_RESULT_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        result = adapter.outbound_request(ir)
        assert json.loads(result) == _normalise(WITH_TOOL_RESULT_REQUEST)

    def test_with_extras(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(WITH_EXTRAS_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        result = adapter.outbound_request(ir)
        assert json.loads(result) == _normalise(WITH_EXTRAS_REQUEST)

    def test_block_level_extras_survive_round_trip(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(WITH_BLOCK_EXTRAS_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        result = adapter.outbound_request(ir)
        assert json.loads(result) == _normalise(WITH_BLOCK_EXTRAS_REQUEST)

    def test_tool_result_extras_survive_round_trip(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(WITH_TOOL_RESULT_EXTRAS_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        result = adapter.outbound_request(ir)
        assert json.loads(result) == _normalise(WITH_TOOL_RESULT_EXTRAS_REQUEST)


# ── metadata unpacking ──────────────────────────────────────────────


class TestMetadataUnpacking:
    def test_user_id_parsed(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(WITH_METADATA_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        assert ir.metadata.session_id == "sess-001"
        assert ir.metadata.device_id == "dev-abc"
        assert ir.metadata.account_id == "acct-xyz"

    def test_metadata_round_trip(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(WITH_METADATA_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        result = adapter.outbound_request(ir)
        assert json.loads(result) == _normalise(WITH_METADATA_REQUEST)

    def test_no_metadata(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(MINIMAL_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        assert ir.metadata.session_id is None
        assert ir.metadata.device_id is None
        assert ir.metadata.account_id is None


# ── model normalisation ─────────────────────────────────────────────


class TestModelNormalisation:
    def test_model_prefixed(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(MINIMAL_REQUEST, sort_keys=True).encode()
        ir = adapter.inbound_request(raw)
        assert ir.model == "anthropic/claude-sonnet-4-20250514"
        assert ir.provider == "anthropic"


# ── response parsing ───────────────────────────────────────────────

SAMPLE_RESPONSE: dict[str, Any] = {
    "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-20250514",
    "stop_reason": "end_turn",
    "usage": {
        "input_tokens": 25,
        "output_tokens": 150,
        "cache_read_input_tokens": 10,
        "cache_creation_input_tokens": 0,
    },
    "content": [
        {"type": "text", "text": "Hello! How can I help?"},
    ],
}


RESPONSE_WITH_THINKING: dict[str, Any] = {
    "id": "msg_01ThinkingExample",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-20250514",
    "stop_reason": "end_turn",
    "usage": {
        "input_tokens": 40,
        "output_tokens": 120,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    },
    "content": [
        {
            "type": "thinking",
            "thinking": "The user wants to know the capital of France.",
            "signature": "sig_abc123",
        },
        {"type": "text", "text": "The capital of France is Paris."},
    ],
}


# A minimal Anthropic SSE stream that produces a thinking block followed
# by a text block. Buffered verbatim so _inbound_response_sse is exercised
# end to end.
SSE_WITH_THINKING_STREAM = (
    'data: {"type":"message_start","message":{"id":"msg_sse_think","model":'
    '"claude-sonnet-4-20250514","usage":{"input_tokens":12,'
    '"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n'
    'data: {"type":"content_block_start","index":0,"content_block":'
    '{"type":"thinking","thinking":""}}\n'
    'data: {"type":"content_block_delta","index":0,"delta":'
    '{"type":"thinking_delta","thinking":"Let me think about this."}}\n'
    'data: {"type":"content_block_stop","index":0}\n'
    'data: {"type":"content_block_start","index":1,"content_block":'
    '{"type":"text","text":""}}\n'
    'data: {"type":"content_block_delta","index":1,"delta":'
    '{"type":"text_delta","text":"Done."}}\n'
    'data: {"type":"content_block_stop","index":1}\n'
    'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
    '"usage":{"output_tokens":7}}\n'
    "data: [DONE]\n"
)


class TestResponseParsing:
    def test_basic_response(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(SAMPLE_RESPONSE).encode()
        resp = adapter.inbound_response(raw, "application/json")
        assert resp.id == "msg_01XFDUDYJgAACzvnptvVoYEL"
        assert resp.model == "anthropic/claude-sonnet-4-20250514"
        assert resp.stop_reason == "end_turn"
        assert resp.usage.input_tokens == 25
        assert resp.usage.output_tokens == 150
        assert resp.usage.cache_read_input_tokens == 10
        assert len(resp.content) == 1

    def test_json_response_with_thinking(self, adapter: AnthropicAdapter) -> None:
        """Thinking blocks in JSON responses carry a 'thinking' field, not 'text'.

        Regression: _parse_response_content previously indexed item["text"]
        and raised KeyError on every response containing a thinking block.
        """
        from transport_matters.ir import TextBlock, ThinkingBlock

        raw = json.dumps(RESPONSE_WITH_THINKING).encode()
        resp = adapter.inbound_response(raw, "application/json")
        assert len(resp.content) == 2
        thinking = resp.content[0]
        assert isinstance(thinking, ThinkingBlock)
        assert thinking.text == "The user wants to know the capital of France."
        assert thinking.provider_data == {"signature": "sig_abc123"}
        text = resp.content[1]
        assert isinstance(text, TextBlock)
        assert text.text == "The capital of France is Paris."

    def test_sse_response_with_thinking(self, adapter: AnthropicAdapter) -> None:
        """SSE stream containing a thinking block parses end to end."""
        from transport_matters.ir import TextBlock, ThinkingBlock

        raw = SSE_WITH_THINKING_STREAM.encode()
        resp = adapter.inbound_response(raw, "text/event-stream")
        assert resp.id == "msg_sse_think"
        assert resp.stop_reason == "end_turn"
        assert resp.usage.input_tokens == 12
        assert resp.usage.output_tokens == 7
        assert len(resp.content) == 2
        thinking = resp.content[0]
        assert isinstance(thinking, ThinkingBlock)
        assert thinking.text == "Let me think about this."
        text = resp.content[1]
        assert isinstance(text, TextBlock)
        assert text.text == "Done."


class TestForwardCompat:
    """inbound_request / inbound_response must never raise on a JSON body.

    Unmodeled or missing fields degrade in place (UnknownBlock for content
    blocks, sentinel defaults for scalars) instead of dropping the whole
    request or response. Triggered in production by provider/CLI version bumps
    (e.g. Claude Code 2.1.154 inlining a {"role":"system"} message).
    """

    def test_unknown_message_role_passes_through(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(
            {
                "model": "claude-opus-4-8",
                "max_tokens": 16,
                "messages": [
                    {"role": "system", "content": [{"type": "text", "text": "s"}]},
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                ],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        assert ir.messages[0].role == "system"
        assert ir.messages[1].role == "user"

    def test_missing_message_role_defaults_to_user(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(
            {
                "model": "m",
                "max_tokens": 16,
                "messages": [{"content": [{"type": "text", "text": "hi"}]}],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        assert ir.messages[0].role == "user"

    def test_text_block_missing_text_degrades_to_unknown(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(
            {
                "model": "m",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": [{"type": "text"}]}],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        assert ir.messages[0].content[0].type == "unknown"

    def test_tool_use_missing_input_degrades_to_unknown(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(
            {
                "model": "m",
                "max_tokens": 16,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": "t", "name": "x"}],
                    }
                ],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        assert ir.messages[0].content[0].type == "unknown"

    def test_image_block_missing_source_degrades_to_unknown(
        self, adapter: AnthropicAdapter
    ) -> None:
        raw = json.dumps(
            {
                "model": "m",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": [{"type": "image"}]}],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        assert ir.messages[0].content[0].type == "unknown"

    def test_tool_result_missing_tool_use_id_degrades_to_unknown(
        self, adapter: AnthropicAdapter
    ) -> None:
        raw = json.dumps(
            {
                "model": "m",
                "max_tokens": 16,
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "tool_result", "content": []}],
                    }
                ],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        assert ir.messages[0].content[0].type == "unknown"

    def test_tool_result_unknown_subblock_shape_degrades(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(
            {
                "model": "m",
                "max_tokens": 16,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "t",
                                "content": [{"type": "text"}],
                            }
                        ],
                    }
                ],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        block = ir.messages[0].content[0]
        assert isinstance(block, ToolResultBlock)
        assert block.content[0].type == "unknown"

    def test_system_string_shorthand(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(
            {
                "model": "m",
                "max_tokens": 16,
                "system": "You are helpful.",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        assert len(ir.system) == 1
        assert ir.system[0].text == "You are helpful."

    def test_server_side_tool_without_schema(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(
            {
                "model": "m",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        assert ir.tools[0].name == "web_search"

    def test_request_missing_model(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(
            {
                "max_tokens": 16,
                "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        assert ir.model == "anthropic/unknown"

    def test_request_missing_max_tokens(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(
            {
                "model": "m",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
            }
        ).encode()
        ir = adapter.inbound_request(raw)
        assert ir.sampling.max_tokens == 0

    def test_error_response_body_does_not_crash(self, adapter: AnthropicAdapter) -> None:
        raw = json.dumps(
            {"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}}
        ).encode()
        res = adapter.inbound_response(raw, "application/json")
        assert res.id == ""
        assert res.model == "anthropic/unknown"


class TestForwardCompatContentShapes:
    """Odd content shapes degrade the offending block, never the whole request."""

    def _req(self, content: object) -> bytes:
        return json.dumps(
            {
                "model": "m",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": content}],
            }
        ).encode()

    def test_tool_result_null_content_degrades_block(self, adapter: AnthropicAdapter) -> None:
        raw = self._req([{"type": "tool_result", "tool_use_id": "t", "content": None}])
        ir = adapter.inbound_request(raw)
        assert ir.messages[0].content[0].type == "unknown"

    def test_tool_result_dict_content_degrades_block(self, adapter: AnthropicAdapter) -> None:
        raw = self._req([{"type": "tool_result", "tool_use_id": "t", "content": {"weird": 1}}])
        ir = adapter.inbound_request(raw)
        assert ir.messages[0].content[0].type == "unknown"

    def test_non_dict_content_element_degrades(self, adapter: AnthropicAdapter) -> None:
        raw = self._req(["bare string element", {"type": "text", "text": "ok"}])
        ir = adapter.inbound_request(raw)
        assert ir.messages[0].content[0].type == "unknown"
        assert ir.messages[0].content[1].type == "text"

    def test_non_dict_tool_result_subblock_degrades(self, adapter: AnthropicAdapter) -> None:
        raw = self._req(
            [{"type": "tool_result", "tool_use_id": "t", "content": ["bare", {"x": 1}]}]
        )
        ir = adapter.inbound_request(raw)
        block = ir.messages[0].content[0]
        assert isinstance(block, ToolResultBlock)
        assert all(b.type == "unknown" for b in block.content)
