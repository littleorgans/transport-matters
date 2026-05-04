"""Exchange list and detail endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from weakref import WeakValueDictionary

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from transport_matters.adapters.anthropic import AnthropicAdapter
from transport_matters.codex.diagnostics import build_codex_transport_diagnostics
from transport_matters.codex.events import CodexSemanticEvent, CodexTurnSummary
from transport_matters.codex.repair import (
    CodexDerivedArtifactsDiagnostic,
    CodexDerivedArtifactsRepairAction,
    CodexDerivedArtifactsStatus,
    repair_codex_derived_artifacts,
    resolve_codex_derived_artifacts,
)
from transport_matters.config import get_settings
from transport_matters.counting import count_before_after, get_counter, get_recent_auth
from transport_matters.exceptions import NotFoundError
from transport_matters.exchange_stats import (
    extract_response_text,
    extract_user_prompt_text,
)
from transport_matters.ir import InternalRequest, InternalResponse
from transport_matters.overrides import OverrideAudit
from transport_matters.storage import StorageBackend, get_storage
from transport_matters.storage.base import (
    ExchangeArtifacts,
    IndexEntry,
    TransportArtifacts,
    TransportDiagnostic,
)

if TYPE_CHECKING:
    from transport_matters.codex.derivation import CodexDerivedTurnArtifacts

logger = logging.getLogger(__name__)

router = APIRouter()

# Per-exchange locks serialize concurrent lazy recounts so the second
# caller picks up the first caller's result from the index instead of
# issuing its own round-trip to count_tokens. Weak values keep the map
# bounded by in-flight recounts instead of every exchange ever opened.
_compute_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_compute_locks_meta: asyncio.Lock = asyncio.Lock()


async def _lock_for(exchange_id: str) -> asyncio.Lock:
    async with _compute_locks_meta:
        lock = _compute_locks.get(exchange_id)
        if lock is None:
            lock = asyncio.Lock()
            _compute_locks[exchange_id] = lock
        return lock


class CodexDerivedArtifactsState(BaseModel):
    status: CodexDerivedArtifactsStatus
    diagnostics: tuple[CodexDerivedArtifactsDiagnostic, ...] = ()
    repair: "CodexDerivedArtifactsRepairState | None" = None


class CodexDerivedArtifactsRepairState(BaseModel):
    action: CodexDerivedArtifactsRepairAction
    status_before: CodexDerivedArtifactsStatus


def _codex_derived_artifacts_state(
    *,
    status: CodexDerivedArtifactsStatus,
    diagnostics: tuple[CodexDerivedArtifactsDiagnostic, ...],
    repair: CodexDerivedArtifactsRepairState | None = None,
) -> CodexDerivedArtifactsState:
    return CodexDerivedArtifactsState(
        status=status,
        diagnostics=diagnostics,
        repair=repair,
    )


async def _resolved_codex_derived_artifacts(
    exchange_id: str,
    artifacts: ExchangeArtifacts,
    storage: StorageBackend,
) -> tuple[CodexDerivedTurnArtifacts | None, CodexDerivedArtifactsState | None]:
    resolution = resolve_codex_derived_artifacts(artifacts)
    if resolution.status == "not_applicable":
        return None, None
    if resolution.status == "supported":
        return resolution.derived, _codex_derived_artifacts_state(
            status=resolution.status,
            diagnostics=resolution.diagnostics,
        )

    repair = await repair_codex_derived_artifacts(storage, exchange_id)
    status = "supported" if repair.derived is not None else repair.status_before
    return repair.derived, _codex_derived_artifacts_state(
        status=status,
        diagnostics=repair.diagnostics,
        repair=CodexDerivedArtifactsRepairState(
            action=repair.action,
            status_before=repair.status_before,
        ),
    )


class ExchangeDetailResponse(BaseModel):
    entry: IndexEntry | None
    request_ir: InternalRequest
    request_curated_ir: InternalRequest | None
    request_audit: OverrideAudit | None
    response_ir: InternalResponse | None
    transport: TransportArtifacts | None
    events: tuple[CodexSemanticEvent, ...] | None = None
    turn: CodexTurnSummary | None = None
    codex_derived_artifacts: CodexDerivedArtifactsState | None = None
    transport_diagnostics: list[TransportDiagnostic]


@router.get("")
async def list_exchanges(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_history: bool = Query(default=False),
    track_id: str | None = Query(default=None),
    storage: StorageBackend = Depends(get_storage),
) -> list[IndexEntry]:
    try:
        run_id = None if include_history else get_settings().run_id
        return await storage.read_index(
            limit=limit,
            offset=offset,
            run_id=run_id,
            track_id=track_id,
        )
    except Exception as exc:
        logger.exception("Failed to read exchange index")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read exchange index",
        ) from exc


@router.get("/{exchange_id}")
async def get_exchange(
    exchange_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> ExchangeDetailResponse:
    try:
        artifacts = await storage.read_exchange(exchange_id)
    except FileNotFoundError as exc:
        raise NotFoundError(detail=f"Exchange {exchange_id} not found") from exc

    entry = await storage.read_index_entry(exchange_id)
    if entry is None:
        raise NotFoundError(detail=f"Exchange {exchange_id} not found")
    derived, codex_derived_artifacts = await _resolved_codex_derived_artifacts(
        exchange_id, artifacts, storage
    )

    return ExchangeDetailResponse(
        entry=entry,
        request_ir=artifacts.request_ir,
        request_curated_ir=artifacts.request_curated_ir,
        request_audit=artifacts.request_audit,
        response_ir=artifacts.response_ir,
        transport=artifacts.transport,
        events=derived.events if derived is not None else None,
        turn=derived.turn if derived is not None else None,
        codex_derived_artifacts=codex_derived_artifacts,
        transport_diagnostics=build_codex_transport_diagnostics(artifacts),
    )


class PipelineTokensResponse(BaseModel):
    tokens_before: int | None
    tokens_after: int | None
    # Null on success (both sides real) or cached hit. One of a small set
    # of codes on a degraded path so curl, future error UI, and log
    # scrapers can discriminate without parsing the message body:
    #
    #   ``counter_unavailable``  addon not loaded / counter not published
    #   ``no_auth``              no live flow seen this session
    #   ``artifact_missing``     exchange artifacts gone from disk
    #   ``counter_failed``       count_tokens returned None for ≥1 side
    #   ``unsupported_provider`` endpoint only implemented for Anthropic
    #
    # We don't surface it in the UI yet — the chars fallback is good
    # enough — but leaving the channel open lets future UI features
    # reason about why a row is stuck without adding a second endpoint.
    reason: str | None = None


class TurnContentResponse(BaseModel):
    user_text: str | None
    response_text: str | None
    stop_reason: str | None


@router.get("/{exchange_id}/turn-content")
async def get_turn_content(
    exchange_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> TurnContentResponse:
    try:
        artifacts = await storage.read_exchange(exchange_id)
    except FileNotFoundError as exc:
        raise NotFoundError(detail=f"Exchange {exchange_id} not found") from exc

    if artifacts.response_ir is None:
        response_text = None
        stop_reason = None
    else:
        response_text = extract_response_text(artifacts.response_ir)
        stop_reason = artifacts.response_ir.stop_reason

    return TurnContentResponse(
        user_text=extract_user_prompt_text(artifacts.request_ir),
        response_text=response_text,
        stop_reason=stop_reason,
    )


@router.get("/{exchange_id}/pipeline_tokens")
async def get_pipeline_tokens(
    exchange_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> PipelineTokensResponse:
    """Return stored pipeline token counts, lazily computing them if missing.

    Live rows get tokens stamped by the addon at the time they were
    captured. Rows from before the counter was wired up (or whose initial
    stamp attempt failed) arrive here with both fields null. The first
    UI open of such a row drives a count_tokens round-trip, writes the
    result into the index, and returns it; subsequent opens see the
    cached value without touching Anthropic again.

    Returns ``{null, null}`` (still 200) when the counter is not
    registered, no live flow has been observed yet (no cached auth),
    the count_tokens call itself fails, or the exchange artifacts are
    missing. The UI treats null as "keep the chars fallback", so the
    degraded case is never worse than the pre-existing view.

    Raises 404 when the exchange does not exist or has no pipeline
    record — pipeline-less rows never ran through the override stage
    and have nothing meaningful to count twice.
    """
    entry = await storage.read_index_entry(exchange_id)
    if entry is None:
        raise NotFoundError(detail=f"Exchange {exchange_id} not found")
    if entry.pipeline is None:
        raise NotFoundError(
            detail=f"Exchange {exchange_id} has no pipeline record",
        )
    if entry.provider != "anthropic":
        return PipelineTokensResponse(
            tokens_before=None,
            tokens_after=None,
            reason="unsupported_provider",
        )

    if (
        entry.pipeline.tokens_before is not None
        and entry.pipeline.tokens_after is not None
    ):
        return PipelineTokensResponse(
            tokens_before=entry.pipeline.tokens_before,
            tokens_after=entry.pipeline.tokens_after,
        )

    lock = await _lock_for(exchange_id)
    async with lock:
        # Re-read inside the lock: a concurrent caller may have just
        # finished the compute and written back, in which case we skip
        # the round-trip entirely. Only a fully-stamped row (both sides
        # non-null) counts as "already computed"; a partial stamp would
        # mean the other side failed last time and deserves a retry,
        # not a sticky null.
        entry = await storage.read_index_entry(exchange_id)
        if entry is None or entry.pipeline is None:
            # Race with a mid-flight delete. Report as artifact_missing
            # since the underlying data is gone from disk.
            return PipelineTokensResponse(
                tokens_before=None, tokens_after=None, reason="artifact_missing"
            )
        if (
            entry.pipeline.tokens_before is not None
            and entry.pipeline.tokens_after is not None
        ):
            return PipelineTokensResponse(
                tokens_before=entry.pipeline.tokens_before,
                tokens_after=entry.pipeline.tokens_after,
            )

        counter = get_counter()
        if counter is None:
            return PipelineTokensResponse(
                tokens_before=None, tokens_after=None, reason="counter_unavailable"
            )
        auth = get_recent_auth()
        if not auth:
            return PipelineTokensResponse(
                tokens_before=None, tokens_after=None, reason="no_auth"
            )

        try:
            artifacts = await storage.read_exchange(exchange_id)
        except FileNotFoundError:
            logger.warning(
                "pipeline_tokens: artifacts missing for %s, returning null",
                exchange_id,
            )
            return PipelineTokensResponse(
                tokens_before=None, tokens_after=None, reason="artifact_missing"
            )

        # Shared with the live addon stamp — see counting.count_before_after
        # for the byte-equality collapse. Passing None for after_payload
        # when curated_ir is absent reuses the one-round-trip fast path.
        adapter = AnthropicAdapter()
        before_payload = adapter.outbound_request(artifacts.request_ir)
        after_payload = (
            adapter.outbound_request(artifacts.request_curated_ir)
            if artifacts.request_curated_ir is not None
            else None
        )
        tokens_before, tokens_after = await count_before_after(
            counter, auth, before_payload, after_payload
        )

        # Persist only when both sides are real. Writing a partial stamp
        # like (42, None) would let the "already stamped" short-circuit
        # above freeze the null side forever — on the next open we would
        # return (42, None) from the cache and never retry the count.
        # Keeping the row at (null, null) on any failure (full or partial)
        # leaves it eligible for a future attempt. The caller still sees
        # whatever we computed this time via the response body.
        if tokens_before is not None and tokens_after is not None:
            try:
                await storage.update_pipeline_tokens(
                    exchange_id, tokens_before, tokens_after
                )
            except Exception:
                logger.exception(
                    "pipeline_tokens: failed to persist for %s", exchange_id
                )
            return PipelineTokensResponse(
                tokens_before=tokens_before,
                tokens_after=tokens_after,
            )

        return PipelineTokensResponse(
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            reason="counter_failed",
        )
