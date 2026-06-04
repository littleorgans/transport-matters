import json

from transport_matters.adapters.anthropic import AnthropicAdapter
from transport_matters.flow_state import RequestFlowState
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
)
from transport_matters.overrides import OverrideAudit


class _Flow:
    def __init__(self) -> None:
        self.id = "flow-http-provisional"
        self.metadata: dict[str, object] = {}
        self.request = _Request()
        self.response: _Response | None = None


class _Request:
    def __init__(self) -> None:
        self.headers = {"x-api-key": "test-key"}


class _Response:
    def __init__(self, body: dict[str, object]) -> None:
        self.headers = {"content-type": "application/json"}
        self._text = json.dumps(body)

    def get_text(self) -> str:
        return self._text


class _SeqCounter:
    def __init__(self, values: list[int | None]) -> None:
        self._iter = iter(values)
        self.payloads: list[bytes] = []
        self.auth_headers: list[dict[str, str]] = []
        self.calls = 0

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
        self.calls += 1
        self.payloads.append(payload)
        self.auth_headers.append(auth_headers)
        return next(self._iter)


def _make_ir(system_text: str) -> InternalRequest:
    return InternalRequest(
        model="claude-3-5-sonnet",
        provider="anthropic",
        system=[SystemPart(text=system_text)],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


def _make_state(
    *,
    provisional_exchange_id: str | None = None,
) -> RequestFlowState:
    adapter = AnthropicAdapter()
    request_ir = _make_ir("original system")
    curated_ir = _make_ir("curated system")
    return RequestFlowState(
        adapter=adapter,
        request_ir=request_ir,
        raw_request=adapter.outbound_request(request_ir),
        curated_request_ir=curated_ir,
        audit=OverrideAudit(entries=[], chars_before=100, chars_after=80),
        mutated_manually=True,
        provisional_exchange_id=provisional_exchange_id,
    )


def _make_codex_state() -> RequestFlowState:
    state = _make_state()
    state.request_ir = state.request_ir.model_copy(
        update={"model": "codex/gpt-5-codex", "provider": "codex"}
    )
    state.curated_request_ir = state.curated_request_ir.model_copy(
        update={"model": "codex/gpt-5-codex", "provider": "codex"}
    )
    request_headers = {
        "session-id": "session-1",
        "thread-id": "thread-1",
        "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
    }
    state.codex_request_headers = request_headers
    return state


def _make_response_body() -> dict[str, object]:
    return {
        "id": "msg_http_finalize",
        "type": "message",
        "role": "assistant",
        "model": "claude-3-5-sonnet",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 25,
            "output_tokens": 150,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 5,
        },
        "content": [{"type": "text", "text": "final text"}],
    }


def _make_noop_state() -> RequestFlowState:
    """A no-op pipeline state: curated IR equals the original, wire bytes differ.

    ``raw_request`` is kept in the original (non-canonical) key order so it
    diverges from the serializer's sorted output, reproducing the case where a
    byte comparison would wrongly record a curated artifact.
    """
    adapter = AnthropicAdapter()
    request_ir = _make_ir("same system")
    wire_bytes = json.dumps(
        {
            "model": "claude-3-5-sonnet",
            "system": [{"type": "text", "text": "same system"}],
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        }
    ).encode()
    return RequestFlowState(
        adapter=adapter,
        request_ir=request_ir,
        raw_request=wire_bytes,
        curated_request_ir=request_ir,
        audit=OverrideAudit(entries=[], chars_before=100, chars_after=100),
        mutated_manually=False,
        provisional_exchange_id=None,
    )
