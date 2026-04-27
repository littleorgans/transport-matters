"""Codex exchange derivation helpers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from manicure.codex.derivation import (
    CODEX_DERIVATION_VERSION,
    CodexDerivedTurnArtifacts,
    CodexIncrementalAdvanceRequest,
    CodexReplayRequest,
    CodexTransportCloseFact,
    CodexTransportMessageFact,
    CodexTurnDerivationContext,
    derive_codex_turn_incremental,
    derive_codex_turn_replay,
)
from manicure.codex.derivation_contract import CodexDerivationOperatorFact
from manicure.codex.session_metadata import (
    codex_session_id_from_header_lookup,
    codex_session_id_from_request_metadata,
)
from manicure.codex.transport import (
    build_codex_transport_artifacts,
    get_codex_transport_state,
)
from manicure.exchange_recorder import (
    _curated_request_raw,
    _persistable_curated_ir,
    emit_exchange,
)
from manicure.exchange_stats import build_pipeline_stats, build_req_stats
from manicure.flow_state import get_request_flow_state
from manicure.storage import CodexTurnListSummary

if TYPE_CHECKING:
    from mitmproxy import http

    from manicure.codex.events import CodexTurnSummary
    from manicure.storage import IndexEntry
    from manicure.storage.base import ExchangeArtifacts, TransportArtifacts

logger = logging.getLogger(__name__)

_CODEX_BREAKPOINT_PAUSED_AT_MS_KEY = "manicure_codex_breakpoint_paused_at_ms"
_CODEX_BREAKPOINT_RELEASED_AT_MS_KEY = "manicure_codex_breakpoint_released_at_ms"


def _clear_codex_breakpoint_lifecycle(flow: http.HTTPFlow) -> None:
    flow.metadata.pop(_CODEX_BREAKPOINT_PAUSED_AT_MS_KEY, None)
    flow.metadata.pop(_CODEX_BREAKPOINT_RELEASED_AT_MS_KEY, None)


def _record_codex_breakpoint_release(
    flow: http.HTTPFlow,
    *,
    paused_at_ms: int,
    released_at_ms: int,
) -> None:
    flow.metadata[_CODEX_BREAKPOINT_PAUSED_AT_MS_KEY] = paused_at_ms
    flow.metadata[_CODEX_BREAKPOINT_RELEASED_AT_MS_KEY] = released_at_ms


def _supported_codex_derived_artifacts(
    artifacts: ExchangeArtifacts,
) -> CodexDerivedTurnArtifacts | None:
    if artifacts.events is None or artifacts.turn is None:
        return None
    try:
        return CodexDerivedTurnArtifacts(events=artifacts.events, turn=artifacts.turn)
    except Exception:
        return None


def _codex_session_id(
    flow: http.HTTPFlow,
    request_state: Any,
) -> str | None:
    session_id = codex_session_id_from_request_metadata(
        request_state.request_ir.metadata
    )
    if session_id is not None:
        return session_id
    return codex_session_id_from_header_lookup(flow.request.headers.get)


def _codex_request_curated_present(request_state: Any) -> bool:
    audit_entries = getattr(request_state.audit, "entries", None)
    return bool(audit_entries) or bool(request_state.mutated_manually)


def _codex_operator_facts(
    flow: http.HTTPFlow,
    request_state: Any,
    *,
    turn_started_at: datetime,
) -> tuple[CodexDerivationOperatorFact, ...]:
    facts: list[CodexDerivationOperatorFact] = []
    if _codex_request_curated_present(request_state):
        facts.append(
            CodexDerivationOperatorFact(
                kind="request_curated",
                ts=turn_started_at,
            )
        )

    paused_at_ms = flow.metadata.get(_CODEX_BREAKPOINT_PAUSED_AT_MS_KEY)
    released_at_ms = flow.metadata.get(_CODEX_BREAKPOINT_RELEASED_AT_MS_KEY)
    if isinstance(paused_at_ms, int) and paused_at_ms > 0:
        facts.append(
            CodexDerivationOperatorFact(
                kind="breakpoint_paused",
                ts=datetime.fromtimestamp(paused_at_ms / 1000, tz=UTC),
            )
        )
    if isinstance(released_at_ms, int) and released_at_ms > 0:
        facts.append(
            CodexDerivationOperatorFact(
                kind="breakpoint_released",
                ts=datetime.fromtimestamp(released_at_ms / 1000, tz=UTC),
            )
        )
    return tuple(facts)


def _codex_transport_message_facts(
    transport: TransportArtifacts,
    *,
    start_index: int = 0,
) -> tuple[CodexTransportMessageFact, ...] | None:
    messages: list[CodexTransportMessageFact] = []
    for message_index, message in enumerate(
        transport.messages[start_index:],
        start=start_index,
    ):
        if message.ts is None:
            return None
        messages.append(
            CodexTransportMessageFact(
                message_index=message_index,
                ts=message.ts,
                direction=message.direction,
                event_type=message.event_type,
                payload_json=message.payload_json,
                dropped=message.dropped,
            )
        )
    return tuple(messages)


def _codex_close_fact(
    transport: TransportArtifacts,
) -> CodexTransportCloseFact | None:
    close = transport.close
    if close is None or close.ts is None:
        return None
    return CodexTransportCloseFact(
        ts=close.ts,
        close_code=close.close_code,
        close_reason=close.close_reason,
    )


def _codex_turn_context(
    *,
    exchange_id: str,
    session_id: str,
    turn_id: str,
    turn_index: int,
    model: str,
    existing_turn: CodexTurnSummary | None = None,
) -> CodexTurnDerivationContext:
    return CodexTurnDerivationContext(
        exchange_id=exchange_id,
        session_id=session_id,
        turn_id=turn_id,
        turn_index=turn_index,
        request_message_index=(
            existing_turn.request_message_index if existing_turn is not None else 0
        ),
        model=existing_turn.model if existing_turn is not None else model,
        derivation_version=(
            existing_turn.derivation_version
            if existing_turn is not None
            else CODEX_DERIVATION_VERSION
        ),
    )


def _replay_codex_derived_artifacts(
    flow: http.HTTPFlow,
    *,
    exchange_id: str,
    request_state: Any,
    transport: TransportArtifacts,
    turn_index: int,
    existing_turn: CodexTurnSummary | None = None,
) -> CodexDerivedTurnArtifacts | None:
    if not transport.messages:
        return None
    transport_messages = _codex_transport_message_facts(transport)
    if transport_messages is None or not transport_messages:
        return None
    session_id = _codex_session_id(flow, request_state)
    if session_id is None:
        return None
    turn_started_at = transport_messages[0].ts
    return derive_codex_turn_replay(
        CodexReplayRequest(
            context=_codex_turn_context(
                exchange_id=exchange_id,
                session_id=session_id,
                turn_id=(
                    existing_turn.turn_id if existing_turn is not None else exchange_id
                ),
                turn_index=turn_index,
                model=request_state.request_ir.model,
                existing_turn=existing_turn,
            ),
            transport_messages=transport_messages,
            operator_facts=_codex_operator_facts(
                flow,
                request_state,
                turn_started_at=turn_started_at,
            ),
            close=_codex_close_fact(transport),
        )
    )


def _advance_codex_derived_artifacts(
    artifacts: CodexDerivedTurnArtifacts,
    *,
    exchange_id: str,
    transport: TransportArtifacts,
) -> CodexDerivedTurnArtifacts | None:
    open_turn = artifacts.turn
    cursor = open_turn.cursor
    if open_turn.status != "open" or cursor is None:
        return artifacts
    transport_messages = _codex_transport_message_facts(
        transport,
        start_index=cursor.next_message_index,
    )
    if transport_messages is None:
        return None
    try:
        advanced = derive_codex_turn_incremental(
            CodexIncrementalAdvanceRequest(
                context=_codex_turn_context(
                    exchange_id=exchange_id,
                    session_id=open_turn.session_id,
                    turn_id=open_turn.turn_id,
                    turn_index=open_turn.turn_index,
                    model=open_turn.model,
                    existing_turn=open_turn,
                ),
                transport_messages=transport_messages,
                close=_codex_close_fact(transport),
                cursor=cursor,
                started_at=open_turn.started_at,
                text_chars=open_turn.text_chars,
                tool_calls=open_turn.tool_calls,
            )
        )
    except ValidationError:
        return None
    return CodexDerivedTurnArtifacts(
        events=(*artifacts.events, *advanced.events),
        turn=advanced.turn,
    )


def _updated_codex_exchange_artifacts(
    existing_artifacts: ExchangeArtifacts,
    *,
    request_state: Any,
    transport: TransportArtifacts,
    derived: CodexDerivedTurnArtifacts | None,
    response_ir: Any | None = None,
) -> ExchangeArtifacts:
    return existing_artifacts.model_copy(
        update={
            "request_raw": request_state.raw_request,
            "request_ir": request_state.request_ir,
            "request_curated_raw": _curated_request_raw(
                request_state.adapter,
                request_state.raw_request,
                request_state.curated_request_ir,
            ),
            "request_curated_ir": _persistable_curated_ir(
                request_state.curated_request_ir,
                request_state.request_ir,
            ),
            "request_audit": request_state.audit,
            "response_ir": response_ir,
            "transport": transport,
            "events": derived.events if derived is not None else None,
            "turn": derived.turn if derived is not None else None,
        }
    )


def _updated_codex_provisional_entry(
    existing_entry: IndexEntry,
    *,
    request_state: Any,
    derived: CodexDerivedTurnArtifacts,
) -> IndexEntry:
    return existing_entry.model_copy(
        update={
            "req": build_req_stats(request_state.curated_request_ir),
            "pipeline": build_pipeline_stats(request_state.audit),
            "codex_turn": CodexTurnListSummary.from_turn(derived.turn),
            "mutated_manually": request_state.mutated_manually,
        }
    )


async def _rewrite_codex_provisional_exchange(
    flow: http.HTTPFlow,
    *,
    force_replay: bool = False,
) -> bool:
    request_state = get_request_flow_state(flow)
    state = get_codex_transport_state(flow)
    exchange_id = state.provisional_exchange_id if state is not None else None
    if request_state is None or state is None or exchange_id is None:
        return False

    from manicure.storage import get_storage

    try:
        storage = await get_storage()
        existing_entry = await storage.read_index_entry(exchange_id)
        if existing_entry is None:
            return False
        existing_artifacts = await storage.read_exchange(exchange_id)
        transport = build_codex_transport_artifacts(flow)
        if transport is None:
            return False

        derived = _supported_codex_derived_artifacts(existing_artifacts)
        if force_replay or derived is None:
            turn_index = (
                state.current_turn_index
                if state.current_turn_index is not None
                else max(0, state.next_turn_index - 1)
            )
            existing_turn = derived.turn if derived is not None else None
            replayed = _replay_codex_derived_artifacts(
                flow,
                exchange_id=exchange_id,
                request_state=request_state,
                transport=transport,
                turn_index=(
                    existing_turn.turn_index
                    if existing_turn is not None
                    else turn_index
                ),
                existing_turn=existing_turn,
            )
            if replayed is None:
                return False
            derived = replayed
        else:
            advanced = _advance_codex_derived_artifacts(
                derived,
                exchange_id=exchange_id,
                transport=transport,
            )
            if advanced is None:
                replayed = _replay_codex_derived_artifacts(
                    flow,
                    exchange_id=exchange_id,
                    request_state=request_state,
                    transport=transport,
                    turn_index=derived.turn.turn_index,
                    existing_turn=derived.turn,
                )
                if replayed is None:
                    return False
                derived = replayed
            else:
                derived = advanced

        updated_entry = _updated_codex_provisional_entry(
            existing_entry,
            request_state=request_state,
            derived=derived,
        )
        await storage.persist_exchange(
            updated_entry,
            _updated_codex_exchange_artifacts(
                existing_artifacts,
                request_state=request_state,
                transport=transport,
                derived=derived,
            ),
        )
        if updated_entry != existing_entry:
            emit_exchange(
                request_state.request_ir,
                updated_entry.req,
                updated_entry.res,
                exchange_id,
                updated_entry.ts,
                updated_entry.run_id,
                updated_entry.mutated_manually,
                updated_entry.pipeline,
                flow_id=flow.id,
                codex_turn=updated_entry.codex_turn,
                track_id=updated_entry.track_id,
                parent_track_id=updated_entry.parent_track_id,
                track_display_name=updated_entry.track_display_name,
                track_role=updated_entry.track_role,
                # Rewrites re-emit from IndexEntry because no TrackAssignment is rebuilt here.
                spawn_anchor=updated_entry.spawn_anchor,
            )
    except Exception:
        logger.exception("Failed to rewrite provisional Codex exchange %s", exchange_id)
        return False
    return True
