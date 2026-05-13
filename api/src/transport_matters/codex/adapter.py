"""Codex websocket request adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from transport_matters.adapters.base import ProviderAdapter
from transport_matters.codex.request_parser import parse_codex_request
from transport_matters.codex.request_serializer import serialize_codex_request
from transport_matters.codex.response_parser import parse_codex_response_sse
from transport_matters.codex.transport import (
    is_codex_http_responses_flow,
    is_codex_websocket_flow,
)

if TYPE_CHECKING:
    from transport_matters.ir import InternalRequest, InternalResponse


class CodexAdapter(ProviderAdapter):
    name = "codex"

    def matches(self, flow: Any) -> bool:
        return hasattr(flow, "request") and (
            is_codex_websocket_flow(flow) or is_codex_http_responses_flow(flow)
        )

    def inbound_request(self, raw_body: bytes) -> InternalRequest:
        return parse_codex_request(raw_body)

    def outbound_request(self, ir: InternalRequest) -> bytes:
        return serialize_codex_request(ir)

    def inbound_response(self, raw_body: bytes, content_type: str) -> InternalResponse:
        if "event-stream" not in content_type:
            raise NotImplementedError(
                "Codex adapter only handles SSE responses on the HTTP "
                f"transport; got content-type {content_type!r}"
            )
        response = parse_codex_response_sse(raw_body)
        if response is None:
            raise ValueError(
                "Codex SSE stream contained no parseable response payloads"
            )
        return response
