"""Generic exchange persistence and broadcast helpers."""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict

from transport_matters import broadcast
from transport_matters.client_version import detect_client_version
from transport_matters.config import get_settings
from transport_matters.counting import TokenCountingClient, _relevant_auth_headers
from transport_matters.exchange_stats import (
    _parse_response_ir,
    build_pipeline_stats,
    build_req_stats,
    stamp_pipeline_tokens,
)
from transport_matters.ir import (
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from transport_matters.request_diff import (
    outbound_request_if_changed,
    request_unchanged,
)
from transport_matters.storage import (
    CodexTurnListSummary,
    IndexEntry,
    PipelineStats,
    ReqStats,
    ResStats,
    SpawnAnchor,
)
from transport_matters.storage.base import (
    ExchangeArtifacts,
    StorageBackend,
    TransportArtifacts,
)
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.track_manager import (
    TrackAssignment,
    assignment_index_fields,
    get_track_manager,
)

if TYPE_CHECKING:
    from mitmproxy import http

    from transport_matters.codex.derivation_contract import CodexDerivedTurnArtifacts
    from transport_matters.flow_state import RequestFlowState
    from transport_matters.overrides import OverrideAudit

logger = logging.getLogger(__name__)
_STORAGE_LAYOUT = DiskStorageLayout()


class _RequestArtifactFields(TypedDict):
    request_raw: bytes
    request_ir: InternalRequest
    request_curated_raw: bytes | None
    request_curated_ir: InternalRequest | None
    request_audit: OverrideAudit | None


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


def _emit_exchange_deleted(exchange_id: str, flow_id: str | None = None) -> None:
    payload: dict[str, object] = {"type": "exchange_deleted", "id": exchange_id}
    if flow_id is not None:
        payload["flow_id"] = flow_id
    broadcast.emit(payload)


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


def _unparsed_model(raw: bytes, adapter_name: str) -> str:
    """Best-effort model from the raw JSON body, with a stable fallback."""
    try:
        decoded = json.loads(raw)
    except Exception:
        return f"{adapter_name}/unparsed"
    model = decoded.get("model") if isinstance(decoded, dict) else None
    return model if isinstance(model, str) and model else f"{adapter_name}/unparsed"


def _unparsed_request_ir(
    raw: bytes,
    adapter_name: str,
    client_version: str | None,
) -> InternalRequest:
    """Fabricate a synthetic IR marking a request we could not parse."""
    provider_extras: dict[str, Any] = {"type": "transport.parse_failure"}
    if client_version is not None:
        provider_extras["client_version"] = client_version
    return InternalRequest(
        model=_unparsed_model(raw, adapter_name),
        provider=adapter_name,
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="[unparsed request]")])],
        sampling=SamplingParams(max_tokens=0),
        metadata=RequestMetadata(),
        provider_extras=provider_extras,
    )


async def _persist_unparsed_exchange(
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
        ir = _unparsed_request_ir(raw, provider_name, client_version)
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
        if not await _persist_exchange(storage, entry, artifacts):
            return
        emit_exchange(ir, req_stats, None, exchange_id, ts, run_id, flow_id=flow.id)
    except Exception:
        logger.exception("Failed to record unparsed request for flow %s", flow.id)


async def _persist_unparsed_http_exchange(
    flow: http.HTTPFlow,
    adapter: Any,  # Any: adapter protocol has no shared base
    codex_http: bool,
) -> None:
    """Record an HTTP request the adapter could not parse (raw bytes preserved)."""
    await _persist_unparsed_exchange(flow, _request_raw_bytes(flow), adapter.name)


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


def _persist_track_assignment(
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


async def _persist_http_exchange(
    flow: http.HTTPFlow,
    request_state: RequestFlowState,
    token_counter: TokenCountingClient | None,
) -> bool:
    if request_state.dropped:
        return await _delete_http_provisional_exchange(flow, request_state)
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
    raw_res, res_ir, res_stats = _extract_response(flow, adapter, exchange_id)
    transport, codex_derived, codex_turn = _derive_codex_http(
        flow, request_state, exchange_id, raw_res, ts
    )
    req_stats = build_req_stats(curated_ir)
    pipeline_stats = await _stamped_pipeline_stats(flow, request_state, token_counter, exchange_id)

    run_id = get_settings().run_id
    track_assignment = _persist_track_assignment(
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
        codex_turn=codex_turn,
        **assignment_index_fields(track_assignment),
    )
    return True


async def _persist_http_provisional_exchange(
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
    track_assignment = _persist_track_assignment(
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
    if not await _persist_exchange(storage, entry, artifacts):
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


async def _delete_http_provisional_exchange(
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
    _emit_exchange_deleted(exchange_id, flow_id=flow.id)
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
    raw_res, res_ir, res_stats = _extract_response(flow, adapter, exchange_id)
    transport, codex_derived, codex_turn = _derive_codex_http(
        flow, request_state, exchange_id, raw_res, existing_entry.ts
    )
    req_stats = build_req_stats(curated_ir)
    pipeline_stats = await _stamped_pipeline_stats(flow, request_state, token_counter, exchange_id)

    run_id = existing_entry.run_id
    _persist_track_assignment(run_id, request_state, res_ir, exchange_id=exchange_id)
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
