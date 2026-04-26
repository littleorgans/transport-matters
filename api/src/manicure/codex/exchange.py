"""Codex specific exchange persistence helpers."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from manicure.codex.exchange_derivation import (
    _advance_codex_derived_artifacts,
    _clear_codex_breakpoint_lifecycle,
    _replay_codex_derived_artifacts,
    _supported_codex_derived_artifacts,
    _updated_codex_exchange_artifacts,
)
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
    _persist_track_assignment,
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
from manicure.storage import CodexTurnListSummary, IndexEntry, ResStats
from manicure.storage.base import ExchangeArtifacts
from manicure.track_manager import assignment_index_fields, get_track_manager

if TYPE_CHECKING:
    from mitmproxy import http

    from manicure.codex.derivation import CodexDerivedTurnArtifacts

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
    turn_index = state.next_turn_index
    ts = datetime.now(UTC)
    ts_slug = ts.strftime("%Y%m%dT%H%M%S")
    derived = (
        _replay_codex_derived_artifacts(
            flow,
            exchange_id=exchange_id,
            request_state=request_state,
            transport=transport,
            turn_index=turn_index,
        )
        if transport is not None
        else None
    )
    run_id = get_settings().run_id
    track_assignment = _persist_track_assignment(run_id, request_state, None)
    entry = IndexEntry(
        id=exchange_id,
        run_id=run_id,
        ts=ts,
        provider=ir.provider,
        model=ir.model,
        path=f"exchanges/{ts_slug}-{exchange_id[:8]}/",
        req=req_stats,
        pipeline=pipeline_stats,
        codex_turn=(
            CodexTurnListSummary.from_turn(derived.turn)
            if derived is not None
            else None
        ),
        mutated_manually=request_state.mutated_manually,
        **assignment_index_fields(track_assignment),
    )
    artifacts = ExchangeArtifacts(
        request_raw=raw_req,
        request_ir=ir,
        request_curated_raw=_curated_request_raw(adapter, raw_req, curated_ir),
        request_curated_ir=_persistable_curated_ir(curated_ir, ir),
        request_audit=audit,
        transport=transport,
        events=derived.events if derived is not None else None,
        turn=derived.turn if derived is not None else None,
    )
    if not await _persist_exchange(storage, entry, artifacts):
        return None

    state.provisional_exchange_id = exchange_id
    state.finalized_exchange_id = None
    state.current_turn_index = turn_index
    state.next_turn_index = turn_index + 1
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
        track_id=track_assignment.track_id if track_assignment else None,
        parent_track_id=track_assignment.parent_track_id if track_assignment else None,
        track_display_name=(
            track_assignment.track_display_name if track_assignment else None
        ),
        track_role=track_assignment.track_role if track_assignment else None,
    )
    return exchange_id


async def _delete_codex_provisional_exchange(flow: http.HTTPFlow) -> bool:
    state = get_codex_transport_state(flow)
    exchange_id = state.provisional_exchange_id if state is not None else None
    if exchange_id is None:
        _clear_codex_breakpoint_lifecycle(flow)
        return True

    from manicure.storage import get_storage

    try:
        storage = await get_storage()
        await storage.delete_exchange(exchange_id)
    except Exception:
        logger.exception("Failed to delete provisional Codex exchange %s", exchange_id)
        return False

    if state is not None:
        if (
            state.current_turn_index is not None
            and state.next_turn_index > 0
            and state.current_turn_index == state.next_turn_index - 1
        ):
            state.next_turn_index -= 1
        state.provisional_exchange_id = None
        state.finalized_exchange_id = None
        state.current_turn_index = None
    _clear_codex_breakpoint_lifecycle(flow)
    _emit_exchange_deleted(exchange_id, flow_id=flow.id)
    return True


async def _persist_codex_exchange(
    flow: http.HTTPFlow,
    summary: Any,
    *,
    message_end: int | None = None,
) -> bool:
    request_state = get_request_flow_state(flow)
    state = get_codex_transport_state(flow)
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
    turn_index = (
        state.current_turn_index
        if state is not None and state.current_turn_index is not None
        else max(0, (state.next_turn_index - 1) if state is not None else 0)
    )
    derived = (
        _replay_codex_derived_artifacts(
            flow,
            exchange_id=exchange_id,
            request_state=request_state,
            transport=transport,
            turn_index=turn_index,
        )
        if transport is not None
        else None
    )
    run_id = get_settings().run_id
    track_assignment = _persist_track_assignment(run_id, request_state, res_ir)
    entry = IndexEntry(
        id=exchange_id,
        run_id=run_id,
        ts=ts,
        provider=ir.provider,
        model=ir.model,
        path=f"exchanges/{ts_slug}-{exchange_id[:8]}/",
        req=req_stats,
        pipeline=pipeline_stats,
        res=res_stats,
        codex_turn=(
            CodexTurnListSummary.from_turn(derived.turn)
            if derived is not None
            else None
        ),
        mutated_manually=request_state.mutated_manually,
        **assignment_index_fields(track_assignment),
    )
    artifacts = ExchangeArtifacts(
        request_raw=raw_req,
        request_ir=ir,
        request_curated_raw=_curated_request_raw(adapter, raw_req, curated_ir),
        request_curated_ir=_persistable_curated_ir(curated_ir, ir),
        request_audit=audit,
        response_ir=res_ir,
        transport=transport,
        events=derived.events if derived is not None else None,
        turn=derived.turn if derived is not None else None,
    )
    if not await _persist_exchange(storage, entry, artifacts):
        return False

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
        track_id=track_assignment.track_id if track_assignment else None,
        parent_track_id=track_assignment.parent_track_id if track_assignment else None,
        track_display_name=(
            track_assignment.track_display_name if track_assignment else None
        ),
        track_role=track_assignment.track_role if track_assignment else None,
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

    exchange_id = provisional_exchange_id or finalized_exchange_id
    if provisional_exchange_id is None:
        if exchange_id is None or summary is None:
            return await _persist_codex_exchange(flow, summary, message_end=message_end)
        existing_entry = await storage.read_index_entry(exchange_id)
        if existing_entry is None:
            return await _persist_codex_exchange(flow, summary, message_end=message_end)
    elif exchange_id is None:
        return await _persist_codex_exchange(flow, summary, message_end=message_end)
    else:
        existing_entry = await storage.read_index_entry(exchange_id)
        if existing_entry is None:
            return await _persist_codex_exchange(flow, summary, message_end=message_end)

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

    existing_derived = _supported_codex_derived_artifacts(existing_artifacts)
    derived: CodexDerivedTurnArtifacts | None
    if existing_derived is not None and existing_derived.turn.status != "open":
        derived = existing_derived
    elif existing_derived is not None:
        derived = _advance_codex_derived_artifacts(
            existing_derived,
            exchange_id=exchange_id,
            transport=transport,
        )
        if derived is None:
            derived = _replay_codex_derived_artifacts(
                flow,
                exchange_id=exchange_id,
                request_state=request_state,
                transport=transport,
                turn_index=existing_derived.turn.turn_index,
                existing_turn=existing_derived.turn,
            )
    else:
        turn_index = (
            state.current_turn_index
            if state is not None and state.current_turn_index is not None
            else max(0, (state.next_turn_index - 1) if state is not None else 0)
        )
        derived = _replay_codex_derived_artifacts(
            flow,
            exchange_id=exchange_id,
            request_state=request_state,
            transport=transport,
            turn_index=turn_index,
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
    artifacts = _updated_codex_exchange_artifacts(
        existing_artifacts,
        request_state=request_state,
        transport=transport,
        derived=persisted_derived,
        response_ir=res_ir,
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
        state.current_turn_index = None
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
        codex_turn=entry.codex_turn,
        track_id=entry.track_id,
        parent_track_id=entry.parent_track_id,
        track_display_name=entry.track_display_name,
        track_role=entry.track_role,
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
