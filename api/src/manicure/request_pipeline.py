"""Request parsing and override pipeline helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from manicure.adapters import get_adapter
from manicure.flow_state import capture_request_flow_state
from manicure.overrides import OverrideAudit, apply_overrides, get_store

if TYPE_CHECKING:
    from mitmproxy import http

    from manicure.ir import InternalRequest

logger = logging.getLogger(__name__)


async def parse_request_ir(
    flow: http.HTTPFlow,
    adapter: Any,  # Any: adapter protocol has no shared base
) -> tuple[bytes, InternalRequest] | None:
    """Decode raw request bytes and parse to IR. Returns None on failure."""
    try:
        req_text = flow.request.get_text()
        if req_text is None:
            return None
        raw = req_text.encode()
        ir = adapter.inbound_request(raw)
        return raw, ir
    except Exception:
        logger.exception("Failed to parse request for flow %s", flow.id)
        return None


def capture_codex_initial_request_ir(
    flow: http.HTTPFlow,
    raw: bytes,
) -> InternalRequest | None:
    """Parse the initial Codex client frame and attach the result to metadata."""
    try:
        adapter = get_adapter(flow)
        ir = adapter.inbound_request(raw)
    except Exception:
        logger.exception("Failed to parse Codex initial frame for flow %s", flow.id)
        return None

    capture_request_flow_state(
        flow,
        adapter=adapter,
        request_ir=ir,
        raw_request=raw,
    )
    return ir


async def run_pipeline(
    ir: InternalRequest,
    flow_id: str,
) -> tuple[InternalRequest, OverrideAudit | None]:
    """Apply overrides from the store to the IR. Never raises."""
    store = get_store()
    if not store.enabled:
        return ir, None

    try:
        curated_ir, audit = apply_overrides(store.get_all(), ir)
    except Exception:
        logger.exception(
            "Override pipeline failed for flow %s, forwarding unmodified", flow_id
        )
        return ir, None

    return curated_ir, audit
