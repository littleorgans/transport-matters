from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from mitmproxy.test import tflow

from transport_matters import flow_state
from transport_matters.addon import TransportMattersAddon
from transport_matters.addon_handlers import handle_response_headers
from transport_matters.response_stream import (
    _STREAM_BUFFER_KEY,
    clear_response_capture,
    install_response_tee,
    restore_streamed_response,
)
from transport_matters.shared_proxy.addon import (
    FLOW_LISTEN_PORT_METADATA_KEY,
    FLOW_RUN_ID_METADATA_KEY,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mitmproxy import http


def _flow(
    *,
    host: str = "api.anthropic.com",
    path: str = "/v1/messages",
    method: str = "POST",
    content_type: str = "text/event-stream",
    status_code: int = 200,
    upstream: bool = True,
) -> http.HTTPFlow:
    flow = tflow.tflow(resp=True)
    assert flow.response is not None
    flow.request.host = host
    flow.request.path = path
    flow.request.method = method
    flow.request.headers.clear()
    flow.response.status_code = status_code
    flow.response.headers.clear()
    if content_type:
        flow.response.headers["content-type"] = content_type
    flow.server_conn.timestamp_start = 1.0 if upstream else None
    return flow


def _stream_callback(flow: http.HTTPFlow) -> Callable[[bytes], bytes]:
    assert flow.response is not None
    assert callable(flow.response.stream)
    return cast("Callable[[bytes], bytes]", flow.response.stream)


def test_response_tee_accumulates_and_passes_chunks_through() -> None:
    flow = _flow()

    install_response_tee(flow, should_stream=True)

    first = b"data: ping\n"
    second = b"data: done\n"
    stream = _stream_callback(flow)
    assert stream(first) is first
    assert stream(b"") == b""
    assert stream(second) is second
    assert bytes(flow.metadata[_STREAM_BUFFER_KEY]) == first + second


def test_response_tee_noops_when_not_selected() -> None:
    flow = _flow()

    install_response_tee(flow, should_stream=False)

    assert flow.response is not None
    assert flow.response.stream is False
    assert _STREAM_BUFFER_KEY not in flow.metadata


def test_restore_streamed_response_reconstructs_body_and_text() -> None:
    flow = _flow()
    assert flow.response is not None
    body = b'data: {"type":"ping"}\n'
    flow.response.raw_content = None
    flow.metadata[_STREAM_BUFFER_KEY] = bytearray(body)

    restore_streamed_response(flow)

    assert flow.response.raw_content == body
    assert flow.response.get_text() == body.decode()
    assert _STREAM_BUFFER_KEY not in flow.metadata


def test_restore_streamed_response_uses_tee_buffer_when_body_is_empty() -> None:
    flow = _flow()
    assert flow.response is not None
    body = b'data: {"type":"late"}\n'
    flow.response.raw_content = b""
    flow.metadata[_STREAM_BUFFER_KEY] = bytearray(body)

    restore_streamed_response(flow)

    assert flow.response.raw_content == body
    assert flow.response.get_text() == body.decode()
    assert _STREAM_BUFFER_KEY not in flow.metadata


def test_restore_streamed_response_without_buffer_keeps_existing_body() -> None:
    flow = _flow()
    assert flow.response is not None
    flow.response.raw_content = b"existing"

    restore_streamed_response(flow)

    assert flow.response.raw_content == b"existing"
    assert _STREAM_BUFFER_KEY not in flow.metadata


def test_clear_response_capture_releases_buffer() -> None:
    flow = _flow()
    flow.metadata[_STREAM_BUFFER_KEY] = bytearray(b"chunk")

    clear_response_capture(flow)

    assert _STREAM_BUFFER_KEY not in flow.metadata


@pytest.mark.parametrize(
    ("content_type", "status_code", "upgrade", "upstream"),
    [
        ("application/json", 200, "", True),
        ("text/event-stream", 101, "", True),
        ("text/event-stream", 200, "websocket", True),
        ("text/event-stream", 200, "", False),
    ],
)
def test_responseheaders_skips_non_streamable_responses(
    content_type: str,
    status_code: int,
    upgrade: str,
    upstream: bool,
) -> None:
    flow = _flow(content_type=content_type, status_code=status_code, upstream=upstream)
    if upgrade:
        flow.request.headers["Upgrade"] = upgrade

    handle_response_headers(flow)

    assert flow.response is not None
    assert flow.response.stream is False
    assert _STREAM_BUFFER_KEY not in flow.metadata


def test_responseheaders_streams_codex_http_without_content_type() -> None:
    flow = _flow(
        host="chatgpt.com",
        path="/backend-api/codex/responses?client=cli",
        content_type="",
    )

    handle_response_headers(flow)

    assert flow.response is not None
    assert callable(flow.response.stream)
    assert _STREAM_BUFFER_KEY in flow.metadata


def test_responseheaders_skips_local_codex_http_response() -> None:
    flow = _flow(
        host="chatgpt.com",
        path="/backend-api/codex/responses",
        content_type="",
        upstream=False,
    )

    handle_response_headers(flow)

    assert flow.response is not None
    assert flow.response.stream is False
    assert _STREAM_BUFFER_KEY not in flow.metadata


def test_stream_buffer_key_does_not_collide_with_flow_metadata_keys() -> None:
    flow_state_keys = {
        value
        for name, value in vars(flow_state).items()
        if name.endswith("_KEY")
        and isinstance(value, str)
        and value.startswith("transport_matters_")
    }
    metadata_keys = {
        *flow_state_keys,
        FLOW_RUN_ID_METADATA_KEY,
        FLOW_LISTEN_PORT_METADATA_KEY,
    }

    assert _STREAM_BUFFER_KEY not in metadata_keys


@pytest.mark.asyncio
async def test_addon_error_clears_capture_on_codex_websocket_skip() -> None:
    flow = _flow(
        host="chatgpt.com",
        path="/backend-api/codex/responses?client=cli",
        method="GET",
    )
    flow.request.headers["Upgrade"] = "websocket"
    flow.metadata[_STREAM_BUFFER_KEY] = bytearray(b"chunk")

    await TransportMattersAddon().error(flow)

    assert _STREAM_BUFFER_KEY not in flow.metadata


@pytest.mark.asyncio
async def test_addon_error_clears_capture_without_request_state() -> None:
    flow = _flow()
    flow.metadata[_STREAM_BUFFER_KEY] = bytearray(b"chunk")

    await TransportMattersAddon().error(flow)

    assert _STREAM_BUFFER_KEY not in flow.metadata
