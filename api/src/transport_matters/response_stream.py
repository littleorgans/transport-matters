"""Flow scoped response streaming capture for mitmproxy."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mitmproxy import http

_STREAM_BUFFER_KEY = "transport_matters_response_stream_buffer"


def install_response_tee(flow: http.HTTPFlow, *, should_stream: bool) -> None:
    """Install a byte preserving response tee when the caller selected streaming."""
    if not should_stream or flow.response is None:
        return

    buffer = bytearray()
    flow.metadata[_STREAM_BUFFER_KEY] = buffer

    def capture_chunk(chunk: bytes) -> bytes:
        if chunk:
            buffer.extend(chunk)
        return chunk

    flow.response.stream = capture_chunk


def restore_streamed_response(flow: http.HTTPFlow) -> None:
    """Restore captured streamed bytes onto the response for existing parsers."""
    buffer = flow.metadata.pop(_STREAM_BUFFER_KEY, None)
    if buffer is None or flow.response is None:
        return
    # mitmproxy 12.2.x streams response data through state_stream_response_body.
    # With store_streamed_bodies at its default False, raw_content is normally None
    # after streaming, but the tee buffer is the source of truth for teed flows.
    flow.response.raw_content = bytes(buffer)


def clear_response_capture(flow: http.HTTPFlow) -> None:
    """Release any response stream buffer stored on the flow."""
    flow.metadata.pop(_STREAM_BUFFER_KEY, None)
