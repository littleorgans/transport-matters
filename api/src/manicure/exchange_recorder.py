"""Generic exchange persistence and broadcast helpers."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from manicure import broadcast
from manicure.config import get_settings
from manicure.counting import TokenCountingClient, _relevant_auth_headers
from manicure.exchange_stats import (
    _parse_response_ir,
    build_pipeline_stats,
    build_req_stats,
    stamp_pipeline_tokens,
)
from manicure.ir import InternalRequest
from manicure.storage import IndexEntry, PipelineStats, ReqStats, ResStats
from manicure.storage.base import ExchangeArtifacts, StorageBackend

if TYPE_CHECKING:
    from mitmproxy import http

    from manicure.flow_state import RequestFlowState

logger = logging.getLogger(__name__)


async def _persist_exchange(
    storage: StorageBackend,
    entry: IndexEntry,
    artifacts: ExchangeArtifacts,
) -> bool:
    """Persist one exchange atomically enough to avoid index only rows."""
    try:
        await storage.persist_exchange(entry, artifacts)
        return True
    except Exception:
        logger.exception("Failed to write exchange %s", entry.id)
        return False


def _curated_request_raw(
    adapter: Any,
    original_raw: bytes,
    curated_ir: InternalRequest,
) -> bytes | None:
    """Return the exact outbound request bytes when they differ from the input."""
    curated_raw = adapter.outbound_request(curated_ir)
    return curated_raw if curated_raw != original_raw else None


def _persistable_curated_ir(
    curated_ir: InternalRequest, original_ir: InternalRequest
) -> InternalRequest | None:
    """Return a validated curated IR snapshot or None when it should not be stored."""
    if curated_ir == original_ir:
        return None
    try:
        return InternalRequest.model_validate(curated_ir.model_dump(mode="python"))
    except Exception:
        logger.warning("Skipping invalid curated IR persistence")
        return None


def emit_exchange(
    ir: InternalRequest,
    req_stats: ReqStats,
    res_stats: ResStats | None,
    exchange_id: str,
    ts: datetime,
    run_id: str | None,
    mutated_manually: bool = False,
    pipeline_stats: PipelineStats | None = None,
    flow_id: str | None = None,
) -> None:
    """Broadcast the exchange event to SSE subscribers."""
    payload: dict[str, object] = {
        "type": "exchange",
        "id": exchange_id,
        "run_id": run_id,
        "ts": ts.isoformat(),
        "provider": ir.provider,
        "model": ir.model,
        "req": req_stats.model_dump(mode="json"),
        "res": res_stats.model_dump(mode="json") if res_stats else None,
        "mutated_manually": mutated_manually,
        "pipeline": pipeline_stats.model_dump(mode="json") if pipeline_stats else None,
    }
    if flow_id is not None:
        payload["flow_id"] = flow_id
    broadcast.emit(payload)


def _emit_exchange_deleted(exchange_id: str, flow_id: str | None = None) -> None:
    payload: dict[str, object] = {"type": "exchange_deleted", "id": exchange_id}
    if flow_id is not None:
        payload["flow_id"] = flow_id
    broadcast.emit(payload)


async def _persist_http_exchange(
    flow: http.HTTPFlow,
    request_state: RequestFlowState,
    token_counter: TokenCountingClient | None,
) -> bool:
    from manicure.storage import get_storage

    storage = await get_storage()
    adapter = request_state.adapter
    ir = request_state.request_ir
    raw_req = request_state.raw_request
    curated_ir = request_state.curated_request_ir
    audit = request_state.audit
    exchange_id = str(uuid.uuid4())
    ts = datetime.now(UTC)
    res_text = flow.response.get_text() if flow.response else None
    raw_res = res_text.encode() if res_text else b""
    content_type = (
        flow.response.headers.get("content-type", "") if flow.response else ""
    )
    res_ir, res_stats = _parse_response_ir(adapter, raw_res, content_type, exchange_id)
    req_stats = build_req_stats(curated_ir)
    pipeline_stats = build_pipeline_stats(audit)
    if pipeline_stats is not None and token_counter is not None:
        try:
            auth = _relevant_auth_headers(flow.request.headers)
            pipeline_stats = await stamp_pipeline_tokens(
                pipeline_stats,
                ir,
                curated_ir,
                adapter,
                token_counter,
                auth,
            )
        except Exception:
            logger.exception(
                "count_tokens stamp failed for %s, leaving tokens unset",
                exchange_id,
            )

    ts_slug = ts.strftime("%Y%m%dT%H%M%S")
    entry = IndexEntry(
        id=exchange_id,
        run_id=get_settings().run_id,
        ts=ts,
        provider=ir.provider,
        model=ir.model,
        path=f"exchanges/{ts_slug}-{exchange_id[:8]}/",
        req=req_stats,
        pipeline=pipeline_stats,
        res=res_stats,
        mutated_manually=request_state.mutated_manually,
    )
    artifacts = ExchangeArtifacts(
        request_raw=raw_req,
        request_ir=ir,
        request_curated_raw=_curated_request_raw(adapter, raw_req, curated_ir),
        request_curated_ir=_persistable_curated_ir(curated_ir, ir),
        request_audit=audit,
        response_raw=raw_res or None,
        response_ir=res_ir,
    )
    if not await _persist_exchange(storage, entry, artifacts):
        return False

    emit_exchange(
        ir,
        req_stats,
        res_stats,
        exchange_id,
        ts,
        get_settings().run_id,
        request_state.mutated_manually,
        pipeline_stats,
        flow_id=flow.id,
    )
    return True
