"""Codex specific exchange persistence helpers."""

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from transport_matters.codex.exchange_derivation import (
    advance_codex_derived_artifacts,
    clear_codex_breakpoint_lifecycle,
    replay_codex_derived_artifacts,
    supported_codex_derived_artifacts,
    updated_codex_exchange_artifacts,
)
from transport_matters.codex.transport import (
    build_codex_response_ir,
    build_codex_response_stats,
    build_codex_transport_artifacts,
    ensure_codex_transport_state,
    get_codex_transport_state,
)
from transport_matters.exchange_recorder import (
    build_request_artifacts,
    emit_exchange,
    emit_exchange_deleted,
    persist_exchange,
    persist_track_assignment,
    persist_unparsed_exchange,
)
from transport_matters.exchange_stats import (
    build_pipeline_stats,
    build_req_stats,
    build_res_stats,
)
from transport_matters.flow_state import get_request_flow_state
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from transport_matters.shared_proxy import ProxyRunBinding, require_run_id, resolve_run_storage
from transport_matters.storage import (
    CodexTurnListSummary,
    IndexEntry,
    PipelineStats,
    ReqStats,
    ResStats,
)
from transport_matters.storage.base import ExchangeArtifacts
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.exchange_sink import emit_to_index
from transport_matters.track_manager import assignment_index_fields, get_track_manager

if TYPE_CHECKING:
    from mitmproxy import http

    from transport_matters.codex.continuity import CodexContinuityAllocation
    from transport_matters.codex.derivation import CodexDerivedTurnArtifacts

logger = logging.getLogger(__name__)
_STORAGE_LAYOUT = DiskStorageLayout()


def _codex_turn_allocation(state: Any | None) -> CodexContinuityAllocation | None:
    if state is None:
        return None
    allocation = getattr(state, "current_turn_allocation", None)
    return allocation if allocation is not None else None


def _codex_turn_index(state: Any | None) -> int:
    allocation = _codex_turn_allocation(state)
    return allocation.turn_index if allocation is not None else 0


async def persist_codex_provisional_exchange(
    flow: http.HTTPFlow,
    binding: ProxyRunBinding | None = None,
) -> str | None:
    state = get_codex_transport_state(flow)
    request_state = get_request_flow_state(flow)
    if state is None or request_state is None:
        return None
    if state.provisional_exchange_id is not None:
        return state.provisional_exchange_id

    storage, run_id = await resolve_run_storage(binding)
    adapter = request_state.adapter
    ir = request_state.request_ir
    raw_req = request_state.raw_request
    curated_ir = request_state.curated_request_ir
    audit = request_state.audit
    transport = build_codex_transport_artifacts(flow)
    req_stats = build_req_stats(curated_ir)
    pipeline_stats = build_pipeline_stats(audit)

    exchange_id = str(uuid.uuid4())
    allocation = _codex_turn_allocation(state)
    turn_index = _codex_turn_index(state)
    ts = datetime.now(UTC)
    derived = (
        replay_codex_derived_artifacts(
            flow,
            exchange_id=exchange_id,
            request_state=request_state,
            transport=transport,
            turn_index=turn_index,
            continuity=allocation,
        )
        if transport is not None
        else None
    )
    track_assignment = persist_track_assignment(
        run_id, request_state, None, exchange_id=exchange_id
    )
    entry = IndexEntry(
        id=exchange_id,
        run_id=run_id,
        ts=ts,
        provider=ir.provider,
        model=ir.model,
        path=_STORAGE_LAYOUT.exchange_index_path_for(exchange_id, ts=ts),
        req=req_stats,
        pipeline=pipeline_stats,
        codex_turn=(CodexTurnListSummary.from_turn(derived.turn) if derived is not None else None),
        mutated_manually=request_state.mutated_manually,
        **assignment_index_fields(track_assignment),
    )
    artifacts = ExchangeArtifacts(
        **build_request_artifacts(adapter, raw_req, ir, curated_ir, audit),
        transport=transport,
        events=derived.events if derived is not None else None,
        turn=derived.turn if derived is not None else None,
    )
    if not await persist_exchange(storage, entry, artifacts):
        return None

    state.provisional_exchange_id = exchange_id
    state.finalized_exchange_id = None
    emit_exchange(
        ir,
        req_stats,
        None,
        exchange_id,
        ts,
        run_id,
        request_state.mutated_manually,
        pipeline_stats,
        flow_id=flow.id,
        codex_turn=entry.codex_turn,
        **assignment_index_fields(track_assignment),
    )
    return exchange_id


async def delete_codex_provisional_exchange(
    flow: http.HTTPFlow,
    binding: ProxyRunBinding | None = None,
) -> bool:
    state = get_codex_transport_state(flow)
    exchange_id = state.provisional_exchange_id if state is not None else None
    if exchange_id is None:
        clear_codex_breakpoint_lifecycle(flow)
        return True

    try:
        storage, run_id = await resolve_run_storage(binding)
        await storage.delete_exchange(exchange_id)
    except Exception:
        logger.exception("Failed to delete provisional Codex exchange %s", exchange_id)
        return False

    if state is not None:
        state.provisional_exchange_id = None
        state.finalized_exchange_id = None
        state.current_turn_allocation = None
    clear_codex_breakpoint_lifecycle(flow)
    emit_exchange_deleted(exchange_id, run_id=run_id, flow_id=flow.id)
    return True


async def _persist_codex_exchange(
    flow: http.HTTPFlow,
    summary: Any,
    *,
    binding: ProxyRunBinding | None = None,
    message_end: int | None = None,
) -> bool:
    request_state = get_request_flow_state(flow)
    state = get_codex_transport_state(flow)
    if request_state is None:
        return False

    storage, run_id = await resolve_run_storage(binding)
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
    allocation = _codex_turn_allocation(state)
    turn_index = _codex_turn_index(state)
    derived = (
        replay_codex_derived_artifacts(
            flow,
            exchange_id=exchange_id,
            request_state=request_state,
            transport=transport,
            turn_index=turn_index,
            continuity=allocation,
        )
        if transport is not None
        else None
    )
    track_assignment = persist_track_assignment(
        run_id, request_state, res_ir, exchange_id=exchange_id
    )
    entry = IndexEntry(
        id=exchange_id,
        run_id=run_id,
        ts=ts,
        provider=ir.provider,
        model=ir.model,
        path=_STORAGE_LAYOUT.exchange_index_path_for(exchange_id, ts=ts),
        req=req_stats,
        pipeline=pipeline_stats,
        res=res_stats,
        codex_turn=(CodexTurnListSummary.from_turn(derived.turn) if derived is not None else None),
        mutated_manually=request_state.mutated_manually,
        **assignment_index_fields(track_assignment),
    )
    artifacts = ExchangeArtifacts(
        **build_request_artifacts(adapter, raw_req, ir, curated_ir, audit),
        response_ir=res_ir,
        transport=transport,
        events=derived.events if derived is not None else None,
        turn=derived.turn if derived is not None else None,
    )
    if not await persist_exchange(storage, entry, artifacts):
        return False

    # Tier-1 persisted. Hand the exchange to the optional post-persist sink, mirroring the
    # Claude recorder. Best-effort: emit_to_index swallows any failure so the wire path never
    # fails because of an observer.
    emit_to_index(entry, artifacts)
    emit_exchange(
        ir,
        req_stats,
        res_stats,
        exchange_id,
        ts,
        run_id,
        request_state.mutated_manually,
        pipeline_stats,
        flow_id=flow.id,
        codex_turn=entry.codex_turn,
        **assignment_index_fields(track_assignment),
    )
    return True


async def finalize_codex_provisional_exchange(
    flow: http.HTTPFlow,
    summary: Any | None,
    binding: ProxyRunBinding | None = None,
    *,
    message_end: int | None = None,
) -> bool:
    request_state = get_request_flow_state(flow)
    state = get_codex_transport_state(flow)
    provisional_exchange_id = state.provisional_exchange_id if state is not None else None
    finalized_exchange_id = state.finalized_exchange_id if state is not None else None
    if request_state is None:
        return False

    storage, _run_id = await resolve_run_storage(binding)

    exchange_id = provisional_exchange_id or finalized_exchange_id
    if provisional_exchange_id is None:
        if exchange_id is None or summary is None:
            return await _persist_codex_exchange(
                flow,
                summary,
                binding=binding,
                message_end=message_end,
            )
        existing_entry = await storage.read_index_entry(exchange_id)
        if existing_entry is None:
            return await _persist_codex_exchange(
                flow,
                summary,
                binding=binding,
                message_end=message_end,
            )
    elif exchange_id is None:
        return await _persist_codex_exchange(
            flow,
            summary,
            binding=binding,
            message_end=message_end,
        )
    else:
        existing_entry = await storage.read_index_entry(exchange_id)
        if existing_entry is None:
            return await _persist_codex_exchange(
                flow,
                summary,
                binding=binding,
                message_end=message_end,
            )

    ir = request_state.request_ir
    existing_artifacts = await storage.read_exchange(exchange_id)
    transport = build_codex_transport_artifacts(flow, summary, message_end=message_end)
    if transport is None:
        return False
    req_stats = build_req_stats(request_state.curated_request_ir)
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
    pipeline_stats = build_pipeline_stats(request_state.audit)

    existing_derived = supported_codex_derived_artifacts(existing_artifacts)
    derived: CodexDerivedTurnArtifacts | None
    if existing_derived is not None and existing_derived.turn.status != "open":
        derived = existing_derived
    elif existing_derived is not None:
        derived = advance_codex_derived_artifacts(
            existing_derived,
            exchange_id=exchange_id,
            transport=transport,
        )
        if derived is None:
            derived = replay_codex_derived_artifacts(
                flow,
                exchange_id=exchange_id,
                request_state=request_state,
                transport=transport,
                turn_index=existing_derived.turn.turn_index,
                existing_turn=existing_derived.turn,
            )
    else:
        allocation = _codex_turn_allocation(state)
        turn_index = _codex_turn_index(state)
        derived = replay_codex_derived_artifacts(
            flow,
            exchange_id=exchange_id,
            request_state=request_state,
            transport=transport,
            turn_index=turn_index,
            continuity=allocation,
        )
    persisted_derived = derived if derived is not None else existing_derived
    if derived is None:
        if persisted_derived is not None:
            logger.warning(
                "Final Codex derivation failed for exchange %s; preserving prior derived artifacts",
                exchange_id,
            )
        else:
            logger.warning(
                "Persisting Codex exchange %s without derived artifacts after derivation failure",
                exchange_id,
            )

    if (
        existing_entry.run_id is not None
        and existing_entry.track_id is not None
        and res_ir is not None
    ):
        get_track_manager().observe_response(
            existing_entry.run_id,
            existing_entry.track_id,
            res_ir,
            exchange_id=existing_entry.id,
        )
    entry = existing_entry.model_copy(
        update={
            "provider": ir.provider,
            "model": ir.model,
            "req": req_stats,
            "pipeline": pipeline_stats,
            "res": res_stats,
            "codex_turn": (
                CodexTurnListSummary.from_turn(persisted_derived.turn)
                if persisted_derived is not None
                else None
            ),
            "mutated_manually": request_state.mutated_manually,
        }
    )
    artifacts = updated_codex_exchange_artifacts(
        existing_artifacts,
        request_state=request_state,
        transport=transport,
        derived=persisted_derived,
        response_ir=res_ir,
    )
    try:
        await storage.persist_exchange(entry, artifacts)
    except Exception:
        logger.exception("Failed to finalize provisional Codex exchange %s", exchange_id)
        return False

    _mark_codex_exchange_finalized(state, exchange_id)
    # Codex's primary streaming durable seam feeds the observer here, exactly once, with the
    # completed exchange. The no-provisional branches return via _persist_codex_exchange above,
    # which emits there, so there is no double emit. Best-effort.
    emit_to_index(entry, artifacts)
    _emit_codex_entry_exchange(
        flow=flow,
        ir=ir,
        entry=entry,
        req_stats=req_stats,
        res_stats=res_stats,
        pipeline_stats=pipeline_stats,
        mutated_manually=request_state.mutated_manually,
    )
    return True


def _mark_codex_exchange_finalized(state: Any | None, exchange_id: str) -> None:
    if state is None:
        return
    state.provisional_exchange_id = None
    state.finalized_exchange_id = exchange_id
    state.current_turn_allocation = None


def _emit_codex_entry_exchange(
    *,
    flow: http.HTTPFlow,
    ir: InternalRequest,
    entry: IndexEntry,
    req_stats: ReqStats,
    res_stats: ResStats,
    pipeline_stats: PipelineStats | None,
    mutated_manually: bool,
) -> None:
    emit_exchange(
        ir,
        req_stats,
        res_stats,
        entry.id,
        entry.ts,
        require_run_id(entry.run_id),
        mutated_manually,
        pipeline_stats,
        flow_id=flow.id,
        codex_turn=entry.codex_turn,
        track_id=entry.track_id,
        parent_track_id=entry.parent_track_id,
        track_display_name=entry.track_display_name,
        track_role=entry.track_role,
        spawn_anchor=entry.spawn_anchor,
    )


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


async def persist_codex_handshake_failure(
    flow: http.HTTPFlow,
    binding: ProxyRunBinding | None = None,
) -> None:
    response = getattr(flow, "response", None)
    if response is None or getattr(response, "status_code", None) == 101:
        return

    ensure_codex_transport_state(flow)
    transport = build_codex_transport_artifacts(flow)
    if transport is None:
        return

    storage, run_id = await resolve_run_storage(binding)
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
    entry = IndexEntry(
        id=exchange_id,
        run_id=run_id,
        ts=ts,
        provider="codex",
        model=ir.model,
        path=_STORAGE_LAYOUT.exchange_index_path_for(exchange_id, ts=ts),
        req=req_stats,
        res=res_stats,
    )
    artifacts = ExchangeArtifacts(
        request_raw=b"",
        request_ir=ir,
        response_raw=response_raw,
        transport=transport,
    )
    if not await persist_exchange(storage, entry, artifacts):
        return

    emit_exchange(
        ir,
        req_stats,
        res_stats,
        exchange_id,
        ts,
        run_id,
        flow_id=flow.id,
    )


async def persist_unparsed_codex_exchange(
    flow: http.HTTPFlow,
    raw_frame: bytes,
    binding: ProxyRunBinding | None = None,
) -> None:
    """Record an unparsable Codex initial frame (raw bytes preserved).

    Skips gracefully when the frame is unavailable; otherwise delegates to the
    shared recorder so HTTP and Codex parse-failures stay identical.
    """
    if not raw_frame:
        return
    await persist_unparsed_exchange(flow, raw_frame, "codex", binding)
