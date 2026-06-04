"""Generic exchange persistence and broadcast helpers."""

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from transport_matters import broadcast
from transport_matters.client_version import detect_client_version
from transport_matters.config import get_settings
from transport_matters.exchange_recorder_artifacts import (
    build_request_artifacts as build_request_artifacts,
)
from transport_matters.exchange_recorder_artifacts import (
    derive_codex_http,
    extract_response,
    request_raw_bytes,
    stamped_pipeline_stats,
)
from transport_matters.exchange_recorder_artifacts import (
    persistable_curated_ir as persistable_curated_ir,
)
from transport_matters.exchange_recorder_artifacts import (
    tag_http_error_status as tag_http_error_status,
)
from transport_matters.exchange_recorder_unparsed import unparsed_request_ir
from transport_matters.exchange_stats import build_pipeline_stats, build_req_stats
from transport_matters.storage import (
    CodexTurnListSummary,
    IndexEntry,
    PipelineStats,
    ReqStats,
    ResStats,
    SpawnAnchor,
)
from transport_matters.storage.base import ExchangeArtifacts, StorageBackend
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.track_manager import (
    TrackAssignment,
    assignment_index_fields,
    get_track_manager,
)

if TYPE_CHECKING:
    from mitmproxy import http

    from transport_matters.counting import TokenCountingClient
    from transport_matters.flow_state import RequestFlowState
    from transport_matters.ir import InternalRequest, InternalResponse

logger = logging.getLogger(__name__)
_STORAGE_LAYOUT = DiskStorageLayout()


async def persist_exchange(
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
    codex_turn: CodexTurnListSummary | None = None,
    track_id: str | None = None,
    parent_track_id: str | None = None,
    track_display_name: str | None = None,
    track_role: str | None = None,
    spawn_anchor: SpawnAnchor | None = None,
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
        "track_id": track_id or run_id,
        "parent_track_id": parent_track_id,
        "track_display_name": track_display_name,
        "track_role": track_role or "parent",
        "spawn_anchor": spawn_anchor.model_dump(mode="json") if spawn_anchor is not None else None,
    }
    if flow_id is not None:
        payload["flow_id"] = flow_id
    if codex_turn is not None:
        payload["codex_turn"] = codex_turn.model_dump(mode="json")
    broadcast.emit(payload)


def emit_exchange_deleted(exchange_id: str, flow_id: str | None = None) -> None:
    payload: dict[str, object] = {"type": "exchange_deleted", "id": exchange_id}
    if flow_id is not None:
        payload["flow_id"] = flow_id
    broadcast.emit(payload)


async def persist_unparsed_exchange(
    flow: http.HTTPFlow,
    raw: bytes,
    provider_name: str,
) -> None:
    """Record a synthetic exchange for traffic the adapter could not parse.

    Shared by the HTTP and Codex-WS seams. Preserves the raw bytes and surfaces
    the exchange live in the UI rather than silently dropping it, tagged with
    the detected client version. Never mutates the wire and never raises: a
    recording failure must not crash the proxy hook.
    """
    try:
        headers = getattr(getattr(flow, "request", None), "headers", None)
        client_version = detect_client_version(headers)
        logger.warning(
            "Unsupported/unparsable request shape from %s; "
            "Transport Matters may need updating to support this client version",
            client_version or "unknown client",
        )
        ir = unparsed_request_ir(raw, provider_name, client_version)
        req_stats = build_req_stats(ir)

        from transport_matters.storage import get_storage

        storage = await get_storage()
        exchange_id = str(uuid.uuid4())
        ts = datetime.now(UTC)
        run_id = get_settings().run_id
        entry = IndexEntry(
            id=exchange_id,
            run_id=run_id,
            ts=ts,
            provider=ir.provider,
            model=ir.model,
            path=_STORAGE_LAYOUT.exchange_index_path_for(exchange_id, ts=ts),
            req=req_stats,
        )
        artifacts = ExchangeArtifacts(request_raw=raw, request_ir=ir)
        if not await persist_exchange(storage, entry, artifacts):
            return
        emit_exchange(ir, req_stats, None, exchange_id, ts, run_id, flow_id=flow.id)
    except Exception:
        logger.exception("Failed to record unparsed request for flow %s", flow.id)


async def persist_unparsed_http_exchange(
    flow: http.HTTPFlow,
    adapter: Any,  # Any: adapter protocol has no shared base
    codex_http: bool,
) -> None:
    """Record an HTTP request the adapter could not parse (raw bytes preserved)."""
    await persist_unparsed_exchange(flow, request_raw_bytes(flow), adapter.name)


def _assign_track(
    run_id: str | None,
    ir: InternalRequest,
    res_ir: InternalResponse | None,
    *,
    exchange_id: str | None = None,
) -> TrackAssignment | None:
    if run_id is None:
        return None
    return get_track_manager().record_exchange(run_id, ir, res_ir, exchange_id=exchange_id)


def persist_track_assignment(
    run_id: str | None,
    request_state: RequestFlowState,
    res_ir: InternalResponse | None,
    *,
    exchange_id: str | None = None,
) -> TrackAssignment | None:
    if run_id is None:
        return None
    if request_state.track_assignment is None:
        return _assign_track(run_id, request_state.request_ir, res_ir, exchange_id=exchange_id)
    if res_ir is not None:
        get_track_manager().observe_response(
            run_id,
            request_state.track_assignment.track_id,
            res_ir,
            exchange_id=exchange_id,
        )
    return request_state.track_assignment


async def persist_http_exchange(
    flow: http.HTTPFlow,
    request_state: RequestFlowState,
    token_counter: TokenCountingClient | None,
) -> bool:
    if request_state.dropped:
        return await delete_http_provisional_exchange(flow, request_state)
    if request_state.provisional_exchange_id is not None:
        finalized = await _finalize_http_provisional_exchange(flow, request_state, token_counter)
        if finalized:
            return True

    from transport_matters.storage import get_storage

    storage = await get_storage()
    adapter = request_state.adapter
    ir = request_state.request_ir
    raw_req = request_state.raw_request
    curated_ir = request_state.curated_request_ir
    audit = request_state.audit
    exchange_id = str(uuid.uuid4())
    ts = datetime.now(UTC)
    raw_res, res_ir, res_stats = extract_response(flow, adapter, exchange_id)
    transport, codex_derived, codex_turn = derive_codex_http(
        flow, request_state, exchange_id, raw_res, ts
    )
    req_stats = build_req_stats(curated_ir)
    pipeline_stats = await stamped_pipeline_stats(flow, request_state, token_counter, exchange_id)

    run_id = get_settings().run_id
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
        codex_turn=codex_turn,
        mutated_manually=request_state.mutated_manually,
        **assignment_index_fields(track_assignment),
    )
    artifacts = ExchangeArtifacts(
        **build_request_artifacts(adapter, raw_req, ir, curated_ir, audit),
        response_raw=raw_res or None,
        response_ir=res_ir,
        transport=transport,
        events=codex_derived.events if codex_derived is not None else None,
        turn=codex_derived.turn if codex_derived is not None else None,
    )
    if not await persist_exchange(storage, entry, artifacts):
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
        codex_turn=codex_turn,
        **assignment_index_fields(track_assignment),
    )
    return True


async def persist_http_provisional_exchange(
    flow: http.HTTPFlow,
    request_state: RequestFlowState,
) -> str | None:
    if request_state.provisional_exchange_id is not None:
        return request_state.provisional_exchange_id

    from transport_matters.storage import get_storage

    storage = await get_storage()
    adapter = request_state.adapter
    ir = request_state.request_ir
    raw_req = request_state.raw_request
    curated_ir = request_state.curated_request_ir
    audit = request_state.audit
    req_stats = build_req_stats(curated_ir)
    pipeline_stats = build_pipeline_stats(audit)

    exchange_id = str(uuid.uuid4())
    ts = datetime.now(UTC)
    run_id = get_settings().run_id
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
        mutated_manually=request_state.mutated_manually,
        **assignment_index_fields(track_assignment),
    )
    artifacts = ExchangeArtifacts(
        **build_request_artifacts(adapter, raw_req, ir, curated_ir, audit),
    )
    if not await persist_exchange(storage, entry, artifacts):
        return None

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
        **assignment_index_fields(track_assignment),
    )
    return exchange_id


async def delete_http_provisional_exchange(
    flow: http.HTTPFlow,
    request_state: RequestFlowState,
) -> bool:
    exchange_id = request_state.provisional_exchange_id
    if exchange_id is None:
        return True

    from transport_matters.flow_state import update_request_flow_state
    from transport_matters.storage import get_storage

    try:
        storage = await get_storage()
        await storage.delete_exchange(exchange_id)
    except Exception:
        logger.exception("Failed to delete provisional HTTP exchange %s", exchange_id)
        return False

    request_state.provisional_exchange_id = None
    update_request_flow_state(flow, provisional_exchange_id=None)
    emit_exchange_deleted(exchange_id, flow_id=flow.id)
    return True


async def _finalize_http_provisional_exchange(
    flow: http.HTTPFlow,
    request_state: RequestFlowState,
    token_counter: TokenCountingClient | None,
) -> bool:
    exchange_id = request_state.provisional_exchange_id
    if exchange_id is None:
        return False

    from transport_matters.storage import get_storage

    storage = await get_storage()
    existing_entry = await storage.read_index_entry(exchange_id)
    if existing_entry is None:
        return False

    adapter = request_state.adapter
    ir = request_state.request_ir
    raw_req = request_state.raw_request
    curated_ir = request_state.curated_request_ir
    audit = request_state.audit
    raw_res, res_ir, res_stats = extract_response(flow, adapter, exchange_id)
    transport, codex_derived, codex_turn = derive_codex_http(
        flow, request_state, exchange_id, raw_res, existing_entry.ts
    )
    req_stats = build_req_stats(curated_ir)
    pipeline_stats = await stamped_pipeline_stats(flow, request_state, token_counter, exchange_id)

    run_id = existing_entry.run_id
    persist_track_assignment(run_id, request_state, res_ir, exchange_id=exchange_id)
    entry = existing_entry.model_copy(
        update={
            "req": req_stats,
            "res": res_stats,
            "pipeline": pipeline_stats,
            "codex_turn": codex_turn,
            "mutated_manually": request_state.mutated_manually,
        }
    )
    existing_artifacts = await storage.read_exchange(exchange_id)
    artifacts = existing_artifacts.model_copy(
        update={
            **build_request_artifacts(adapter, raw_req, ir, curated_ir, audit),
            "response_raw": raw_res or None,
            "response_ir": res_ir,
            "transport": transport,
            "events": codex_derived.events if codex_derived is not None else None,
            "turn": codex_derived.turn if codex_derived is not None else None,
        }
    )
    try:
        await storage.persist_exchange(entry, artifacts)
    except Exception:
        logger.exception("Failed to finalize provisional HTTP exchange %s", exchange_id)
        return False

    emit_exchange(
        ir,
        req_stats,
        res_stats,
        exchange_id,
        existing_entry.ts,
        run_id,
        request_state.mutated_manually,
        pipeline_stats,
        flow_id=flow.id,
        codex_turn=codex_turn,
        track_id=entry.track_id,
        parent_track_id=entry.parent_track_id,
        track_display_name=entry.track_display_name,
        track_role=entry.track_role,
        spawn_anchor=entry.spawn_anchor,
    )
    return True
