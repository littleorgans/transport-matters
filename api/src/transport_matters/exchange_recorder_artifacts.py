"""Exchange artifact construction helpers."""

import logging
from typing import TYPE_CHECKING, Any, TypedDict

from transport_matters.counting import TokenCountingClient, _relevant_auth_headers
from transport_matters.exchange_stats import (
    _parse_response_ir,
    build_pipeline_stats,
    stamp_pipeline_tokens,
)
from transport_matters.ir import InternalRequest, InternalResponse
from transport_matters.request_diff import outbound_request_if_changed, request_unchanged
from transport_matters.storage import CodexTurnListSummary, PipelineStats, ResStats

if TYPE_CHECKING:
    from datetime import datetime

    from mitmproxy import http

    from transport_matters.codex.derivation_contract import CodexDerivedTurnArtifacts
    from transport_matters.flow_state import RequestFlowState
    from transport_matters.overrides import OverrideAudit
    from transport_matters.storage.base import TransportArtifacts

logger = logging.getLogger(__name__)


class _RequestArtifactFields(TypedDict):
    request_raw: bytes
    request_ir: InternalRequest
    request_curated_raw: bytes | None
    request_curated_ir: InternalRequest | None
    request_audit: OverrideAudit | None


def _persistable_curated_ir(
    curated_ir: InternalRequest, original_ir: InternalRequest
) -> InternalRequest | None:
    """Return a validated curated IR snapshot or None when it should not be stored."""
    if request_unchanged(original_ir, curated_ir):
        return None
    try:
        return InternalRequest.model_validate(curated_ir.model_dump(mode="python"))
    except Exception:
        logger.warning("Skipping invalid curated IR persistence")
        return None


def _codex_turn_list_summary(
    derived: CodexDerivedTurnArtifacts | None,
) -> CodexTurnListSummary | None:
    if derived is None:
        return None
    return CodexTurnListSummary.from_turn(derived.turn)


def _codex_http_transport_artifacts(
    flow: http.HTTPFlow,
    *,
    raw_request: bytes,
    raw_response: bytes,
    ts: datetime,
) -> TransportArtifacts | None:
    from transport_matters.codex.transport import build_codex_http_transport_artifacts

    return build_codex_http_transport_artifacts(
        flow,
        raw_request=raw_request,
        raw_response=raw_response,
        ts=ts,
    )


def build_request_artifacts(
    adapter: Any,
    raw_req: bytes,
    ir: InternalRequest,
    curated_ir: InternalRequest,
    audit: OverrideAudit | None,
) -> _RequestArtifactFields:
    return {
        "request_raw": raw_req,
        "request_ir": ir,
        "request_curated_raw": outbound_request_if_changed(adapter, ir, curated_ir),
        "request_curated_ir": _persistable_curated_ir(curated_ir, ir),
        "request_audit": audit,
    }


def _http_error_response_stats(
    flow: http.HTTPFlow,
    raw_res: bytes,
) -> ResStats | None:
    response = getattr(flow, "response", None)
    status_code = getattr(response, "status_code", None)
    if not isinstance(status_code, int) or status_code < 400:
        return None
    response_text = raw_res.decode("utf-8", errors="replace")
    return ResStats(
        stop_reason=f"http_{status_code}",
        text_chars=len(response_text),
    )


def _tag_http_error_status(
    res_stats: ResStats | None,
    flow: http.HTTPFlow,
    raw_res: bytes,
) -> ResStats | None:
    """Tag an HTTP error status (>=400) onto the response stats.

    Adapters now degrade rather than raise on error bodies (e.g. a 429 with no
    'id'), so error tagging keys on the status code, not on a parse failure.
    When the body did parse into usable stats, the parsed token usage is kept
    and only the stop_reason is overridden with http_{status}.
    """
    error_stats = _http_error_response_stats(flow, raw_res)
    if error_stats is None:
        return res_stats
    if res_stats is None:
        return error_stats
    # Error status + body size win (error_stats); carry over any parsed token
    # usage so a billed error response does not lose its accounting.
    return error_stats.model_copy(
        update={
            "input_tokens": res_stats.input_tokens,
            "output_tokens": res_stats.output_tokens,
            "cache_creation_input_tokens": res_stats.cache_creation_input_tokens,
            "cache_read_input_tokens": res_stats.cache_read_input_tokens,
            "tool_calls": res_stats.tool_calls,
        }
    )


def _extract_response(
    flow: http.HTTPFlow,
    adapter: Any,
    exchange_id: str,
) -> tuple[bytes, InternalResponse | None, ResStats | None]:
    res_text = flow.response.get_text() if flow.response else None
    raw_res = res_text.encode() if res_text else b""
    content_type = flow.response.headers.get("content-type", "") if flow.response else ""
    res_ir, res_stats = _parse_response_ir(adapter, raw_res, content_type, exchange_id)
    return raw_res, res_ir, _tag_http_error_status(res_stats, flow, raw_res)


def _derive_codex_http(
    flow: http.HTTPFlow,
    request_state: RequestFlowState,
    exchange_id: str,
    raw_res: bytes,
    ts: datetime,
) -> tuple[
    TransportArtifacts | None,
    CodexDerivedTurnArtifacts | None,
    CodexTurnListSummary | None,
]:
    ir = request_state.request_ir
    if ir.provider != "codex":
        return None, None, None

    from transport_matters.codex.http_derivation import derive_codex_http_turn

    raw_req = request_state.raw_request
    derived = derive_codex_http_turn(
        exchange_id=exchange_id,
        raw_request=raw_req,
        raw_response=raw_res,
        request_headers=request_state.codex_request_headers,
        model=ir.model,
        ts=ts,
    )
    return (
        _codex_http_transport_artifacts(
            flow,
            raw_request=raw_req,
            raw_response=raw_res,
            ts=ts,
        ),
        derived,
        _codex_turn_list_summary(derived),
    )


async def _stamped_pipeline_stats(
    flow: http.HTTPFlow,
    request_state: RequestFlowState,
    token_counter: TokenCountingClient | None,
    exchange_id: str,
) -> PipelineStats | None:
    pipeline_stats = build_pipeline_stats(request_state.audit)
    if pipeline_stats is None or token_counter is None:
        return pipeline_stats
    try:
        auth = _relevant_auth_headers(flow.request.headers)
        return await stamp_pipeline_tokens(
            pipeline_stats,
            request_state.request_ir,
            request_state.curated_request_ir,
            request_state.adapter,
            token_counter,
            auth,
        )
    except Exception:
        logger.exception(
            "count_tokens stamp failed for %s, leaving tokens unset",
            exchange_id,
        )
        return pipeline_stats


def _request_raw_bytes(flow: http.HTTPFlow) -> bytes:
    """Capture the request body binary-safely, never raising on bad bodies.

    Prefers the content-decoded body (what the adapter parsed and the rest of
    the system stores via get_text) so a content-encoded request is recorded as
    readable JSON rather than compressed bytes; falls back to raw bytes.
    """
    request = getattr(flow, "request", None)
    if request is None:
        return b""
    try:
        text = request.get_text()
    except Exception:
        text = None
    if isinstance(text, str):
        return text.encode("utf-8", errors="replace")
    for attr in ("content", "raw_content"):
        value = getattr(request, attr, None)
        if isinstance(value, bytes):
            return value
    return b""
