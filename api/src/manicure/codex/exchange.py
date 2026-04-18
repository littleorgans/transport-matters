"""Codex specific exchange persistence helpers."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from manicure.codex.transport import (
    build_codex_response_ir,
    build_codex_response_stats,
    build_codex_transport_artifacts,
    ensure_codex_transport_state,
    get_codex_transport_state,
)
from manicure.config import get_settings
from manicure.exchange_recorder import (
    _curated_request_raw,
    _emit_exchange_deleted,
    _persist_exchange,
    _persistable_curated_ir,
    emit_exchange,
)
from manicure.exchange_stats import (
    build_pipeline_stats,
    build_req_stats,
    build_res_stats,
)
from manicure.flow_state import get_request_flow_state
from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from manicure.storage import IndexEntry, ResStats
from manicure.storage.base import ExchangeArtifacts

if TYPE_CHECKING:
    from mitmproxy import http

logger = logging.getLogger(__name__)


async def _persist_codex_provisional_exchange(flow: http.HTTPFlow) -> str | None:
    state = get_codex_transport_state(flow)
    request_state = get_request_flow_state(flow)
    if state is None or request_state is None:
        return None
    if state.provisional_exchange_id is not None:
        return state.provisional_exchange_id

    from manicure.storage import get_storage

    storage = await get_storage()
    adapter = request_state.adapter
    ir = request_state.request_ir
    raw_req = request_state.raw_request
    curated_ir = request_state.curated_request_ir
    audit = request_state.audit
    transport = build_codex_transport_artifacts(flow)
    req_stats = build_req_stats(curated_ir)
    pipeline_stats = build_pipeline_stats(audit)

    exchange_id = str(uuid.uuid4())
    ts = datetime.now(UTC)
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
        mutated_manually=request_state.mutated_manually,
    )
    artifacts = ExchangeArtifacts(
        request_raw=raw_req,
        request_ir=ir,
        request_curated_raw=_curated_request_raw(adapter, raw_req, curated_ir),
        request_curated_ir=_persistable_curated_ir(curated_ir, ir),
        request_audit=audit,
        transport=transport,
    )
    if not await _persist_exchange(storage, entry, artifacts):
        return None

    state.provisional_exchange_id = exchange_id
    state.finalized_exchange_id = None
    emit_exchange(
        ir,
        req_stats,
        None,
        exchange_id,
        ts,
        get_settings().run_id,
        request_state.mutated_manually,
        pipeline_stats,
        flow_id=flow.id,
    )
    return exchange_id


async def _delete_codex_provisional_exchange(flow: http.HTTPFlow) -> bool:
    state = get_codex_transport_state(flow)
    exchange_id = state.provisional_exchange_id if state is not None else None
    if exchange_id is None:
        return True

    from manicure.storage import get_storage

    try:
        storage = await get_storage()
        await storage.delete_exchange(exchange_id)
    except Exception:
        logger.exception("Failed to delete provisional Codex exchange %s", exchange_id)
        return False

    if state is not None:
        state.provisional_exchange_id = None
        state.finalized_exchange_id = None
    _emit_exchange_deleted(exchange_id, flow_id=flow.id)
    return True


async def _persist_codex_exchange(
    flow: http.HTTPFlow,
    summary: Any,
    *,
    message_end: int | None = None,
) -> bool:
    request_state = get_request_flow_state(flow)
    if request_state is None:
        return False

    from manicure.storage import get_storage

    storage = await get_storage()
    adapter = request_state.adapter
    ir = request_state.request_ir
    raw_req = request_state.raw_request
    curated_ir = request_state.curated_request_ir
    audit = request_state.audit
    transport = build_codex_transport_artifacts(flow, summary, message_end=message_end)
    req_stats = build_req_stats(curated_ir)
    res_ir = build_codex_response_ir(
        flow,
        summary,
        message_end=message_end,
        default_model=ir.model,
    )
    res_stats = (
        build_res_stats(res_ir)
        if res_ir is not None
        else build_codex_response_stats(flow, summary, message_end=message_end)
    )
    pipeline_stats = build_pipeline_stats(audit)

    exchange_id = str(uuid.uuid4())
    ts = datetime.now(UTC)
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
        response_ir=res_ir,
        transport=transport,
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


async def _finalize_codex_provisional_exchange(
    flow: http.HTTPFlow,
    summary: Any | None,
    *,
    message_end: int | None = None,
) -> bool:
    request_state = get_request_flow_state(flow)
    state = get_codex_transport_state(flow)
    provisional_exchange_id = (
        state.provisional_exchange_id if state is not None else None
    )
    finalized_exchange_id = state.finalized_exchange_id if state is not None else None
    if request_state is None:
        return False

    from manicure.storage import get_storage

    storage = await get_storage()

    if provisional_exchange_id is None:
        if finalized_exchange_id is None or summary is None:
            return await _persist_codex_exchange(flow, summary, message_end=message_end)

        existing_entry = await storage.read_index_entry(finalized_exchange_id)
        if existing_entry is None:
            return await _persist_codex_exchange(flow, summary, message_end=message_end)
    else:
        existing_entry = await storage.read_index_entry(provisional_exchange_id)
        if existing_entry is None:
            return await _persist_codex_exchange(flow, summary, message_end=message_end)

    exchange_id = provisional_exchange_id or finalized_exchange_id
    if exchange_id is None:
        return await _persist_codex_exchange(flow, summary, message_end=message_end)

    adapter = request_state.adapter
    ir = request_state.request_ir
    raw_req = request_state.raw_request
    curated_ir = request_state.curated_request_ir
    audit = request_state.audit
    transport = build_codex_transport_artifacts(flow, summary, message_end=message_end)
    req_stats = build_req_stats(curated_ir)
    res_ir = build_codex_response_ir(
        flow,
        summary,
        message_end=message_end,
        default_model=ir.model,
    )
    res_stats = (
        build_res_stats(res_ir)
        if res_ir is not None
        else build_codex_response_stats(flow, summary, message_end=message_end)
    )
    pipeline_stats = build_pipeline_stats(audit)

    entry = existing_entry.model_copy(
        update={
            "provider": ir.provider,
            "model": ir.model,
            "req": req_stats,
            "pipeline": pipeline_stats,
            "res": res_stats,
            "mutated_manually": request_state.mutated_manually,
        }
    )
    artifacts = ExchangeArtifacts(
        request_raw=raw_req,
        request_ir=ir,
        request_curated_raw=_curated_request_raw(adapter, raw_req, curated_ir),
        request_curated_ir=_persistable_curated_ir(curated_ir, ir),
        request_audit=audit,
        response_ir=res_ir,
        transport=transport,
    )
    try:
        await storage.persist_exchange(entry, artifacts)
    except Exception:
        logger.exception(
            "Failed to finalize provisional Codex exchange %s", exchange_id
        )
        return False

    if state is not None:
        state.provisional_exchange_id = None
        state.finalized_exchange_id = exchange_id
    emit_exchange(
        ir,
        req_stats,
        res_stats,
        exchange_id,
        entry.ts,
        entry.run_id,
        request_state.mutated_manually,
        pipeline_stats,
        flow_id=flow.id,
    )
    return True


def _codex_handshake_failure_ir(flow: http.HTTPFlow) -> InternalRequest:
    response = getattr(flow, "response", None)
    status = getattr(response, "status_code", None)
    summary = "Codex websocket upgrade failed before the initial response.create frame."
    if status is not None:
        summary = f"{summary} upgrade status={status}."
    return InternalRequest(
        model="codex/transport-handshake",
        provider="codex",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text=summary)])],
        sampling=SamplingParams(max_tokens=0),
        metadata=RequestMetadata(
            provider_metadata={
                "transport_error": "websocket_handshake_failed",
                "upgrade_host": getattr(flow.request, "host", ""),
                "upgrade_path": getattr(flow.request, "path", ""),
                "upgrade_status_code": status,
            }
        ),
        stream=False,
        provider_extras={
            "type": "transport.handshake_failure",
        },
    )


async def _persist_codex_handshake_failure(flow: http.HTTPFlow) -> None:
    response = getattr(flow, "response", None)
    if response is None or getattr(response, "status_code", None) == 101:
        return

    ensure_codex_transport_state(flow)
    transport = build_codex_transport_artifacts(flow)
    if transport is None:
        return

    from manicure.storage import get_storage

    storage = await get_storage()
    ir = _codex_handshake_failure_ir(flow)
    req_stats = build_req_stats(ir)
    response_raw = bytes(getattr(response, "raw_content", b"") or b"")
    response_text = response_raw.decode("utf-8", errors="replace")
    res_stats = ResStats(
        stop_reason="websocket_handshake_failed",
        text_chars=len(response_text),
    )

    exchange_id = str(uuid.uuid4())
    ts = datetime.now(UTC)
    ts_slug = ts.strftime("%Y%m%dT%H%M%S")
    entry = IndexEntry(
        id=exchange_id,
        run_id=get_settings().run_id,
        ts=ts,
        provider="codex",
        model=ir.model,
        path=f"exchanges/{ts_slug}-{exchange_id[:8]}/",
        req=req_stats,
        res=res_stats,
    )
    artifacts = ExchangeArtifacts(
        request_raw=b"",
        request_ir=ir,
        response_raw=response_raw,
        transport=transport,
    )
    if not await _persist_exchange(storage, entry, artifacts):
        return

    emit_exchange(
        ir,
        req_stats,
        res_stats,
        exchange_id,
        ts,
        get_settings().run_id,
        flow_id=flow.id,
    )
