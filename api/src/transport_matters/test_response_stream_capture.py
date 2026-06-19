from __future__ import annotations

from typing import TYPE_CHECKING, cast

from mitmproxy.test import tflow

from transport_matters import exchange_recorder as recorder
from transport_matters._exchange_recorder_http_support import _make_state
from transport_matters.addon_handlers import handle_response, handle_response_headers
from transport_matters.flow_state import capture_request_flow_state, update_request_flow_state
from transport_matters.storage import get_storage

if TYPE_CHECKING:
    from collections.abc import Callable

    from mitmproxy import http

    from transport_matters.storage.base import ExchangeArtifacts, IndexEntry

pytest_plugins = ("transport_matters._exchange_recorder_http_fixtures",)

ANTHROPIC_SSE_BODY = (
    b'data: {"type":"message_start","message":{"id":"msg_stream",'
    b'"model":"claude-sonnet-4-20250514","usage":{"input_tokens":25,'
    b'"cache_read_input_tokens":10,"cache_creation_input_tokens":5}}}\n'
    b'data: {"type":"content_block_start","index":0,'
    b'"content_block":{"type":"text","text":""}}\n'
    b'data: {"type":"content_block_delta","index":0,'
    b'"delta":{"type":"text_delta","text":"final text"}}\n'
    b'data: {"type":"content_block_stop","index":0}\n'
    b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
    b'"usage":{"output_tokens":150}}\n'
    b"data: [DONE]\n"
)


def _flow(flow_id: str) -> http.HTTPFlow:
    flow = tflow.tflow(resp=True)
    assert flow.response is not None
    flow.id = flow_id
    flow.request.host = "api.anthropic.com"
    flow.request.path = "/v1/messages"
    flow.request.method = "POST"
    flow.request.headers.clear()
    flow.request.headers["x-api-key"] = "test-key"
    flow.response.status_code = 200
    flow.response.headers.clear()
    flow.response.headers["content-type"] = "text/event-stream"
    flow.server_conn.timestamp_start = 1.0
    return flow


def _stream_callback(flow: http.HTTPFlow) -> Callable[[bytes], bytes]:
    assert flow.response is not None
    assert callable(flow.response.stream)
    return cast("Callable[[bytes], bytes]", flow.response.stream)


async def _finalize_provisional(
    flow_id: str,
    *,
    streamed: bool,
) -> tuple[IndexEntry, ExchangeArtifacts]:
    state = _make_state()
    flow = _flow(flow_id)
    assert flow.response is not None
    exchange_id = await recorder.persist_http_provisional_exchange(flow, state)
    assert exchange_id is not None
    state.provisional_exchange_id = exchange_id
    capture_request_flow_state(
        flow,
        adapter=state.adapter,
        request_ir=state.request_ir,
        raw_request=state.raw_request,
        curated_request_ir=state.curated_request_ir,
        audit=state.audit,
        mutated_manually=state.mutated_manually,
    )
    update_request_flow_state(flow, provisional_exchange_id=exchange_id)

    if streamed:
        flow.response.raw_content = None
        handle_response_headers(flow)
        stream = _stream_callback(flow)
        early_chunk = ANTHROPIC_SSE_BODY[:80]
        assert stream(early_chunk) is early_chunk
        assert flow.response.raw_content is None
        assert stream(ANTHROPIC_SSE_BODY[80:]) == ANTHROPIC_SSE_BODY[80:]
        assert stream(b"") == b""
    else:
        flow.response.raw_content = ANTHROPIC_SSE_BODY

    await handle_response(flow, None)

    storage = await get_storage()
    entry = await storage.read_index_entry(exchange_id)
    assert entry is not None
    artifacts = await storage.read_exchange(exchange_id)
    return entry, artifacts


async def test_streamed_provisional_finalize_matches_buffered_response() -> None:
    buffered_entry, buffered_artifacts = await _finalize_provisional(
        "flow-buffered",
        streamed=False,
    )
    streamed_entry, streamed_artifacts = await _finalize_provisional(
        "flow-streamed",
        streamed=True,
    )

    assert streamed_artifacts.response_raw == buffered_artifacts.response_raw
    assert streamed_artifacts.response_raw == ANTHROPIC_SSE_BODY
    assert streamed_artifacts.response_ir == buffered_artifacts.response_ir
    assert streamed_entry.res == buffered_entry.res
    assert streamed_entry.res is not None
    assert streamed_entry.res.text_chars == len("final text")
