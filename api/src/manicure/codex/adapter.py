"""Codex websocket request adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from manicure.adapters.base import ProviderAdapter
from manicure.codex.request_parser import parse_codex_request
from manicure.codex.request_serializer import serialize_codex_request
from manicure.codex.transport import is_codex_websocket_flow

if TYPE_CHECKING:
    from manicure.ir import InternalRequest, InternalResponse


class CodexAdapter(ProviderAdapter):
    name = "codex"

    def matches(self, flow: Any) -> bool:
        return hasattr(flow, "request") and is_codex_websocket_flow(flow)

    def inbound_request(self, raw_body: bytes) -> InternalRequest:
        return parse_codex_request(raw_body)

    def outbound_request(self, ir: InternalRequest) -> bytes:
        return serialize_codex_request(ir)

    def inbound_response(self, raw_body: bytes, content_type: str) -> InternalResponse:
        raise NotImplementedError("Codex response parsing belongs to a later slice")
