"""Round-trip tests for the Anthropic adapter.

Each test builds a realistic Anthropic request body, runs it through
``inbound_request`` then ``outbound_request``, and asserts lossless
round-trip (modulo key ordering and whitespace).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from manicure.adapters.anthropic import AnthropicAdapter


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
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": "Read /tmp/foo"}]}
    ],
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
                    "text": "Let me consider...",
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
