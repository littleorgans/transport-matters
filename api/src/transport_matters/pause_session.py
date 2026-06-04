"""Breakpoint pause and release helpers."""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from transport_matters import breakpoint as bp
from transport_matters import broadcast
from transport_matters.codex.exchange import delete_codex_provisional_exchange
from transport_matters.codex.exchange_derivation import (
    clear_codex_breakpoint_lifecycle,
    record_codex_breakpoint_release,
    rewrite_codex_provisional_exchange,
)
from transport_matters.codex.transport import (
    get_codex_transport_state,
    mark_codex_initial_request_dropped,
)
from transport_matters.config import get_settings
from transport_matters.counting import TokenCountingClient, relevant_auth_headers
from transport_matters.flow_state import (
    get_request_flow_state,
    update_request_flow_state,
)
from transport_matters.request_diff import outbound_request_if_changed

if TYPE_CHECKING:
    from collections.abc import Callable

    from mitmproxy import http

    from transport_matters.ir import InternalRequest
    from transport_matters.overrides import OverrideAudit
    from transport_matters.storage.base import SpawnAnchor

logger = logging.getLogger(__name__)


class TrackFields(TypedDict):
    run_id: str | None
    track_id: str | None
    parent_track_id: str | None
    track_display_name: str | None
    track_role: Literal["parent", "subagent"] | None
    spawn_anchor: SpawnAnchor | None


@dataclass(frozen=True)
class _PauseHooks:
    auth_headers: dict[str, str] | None = None
    provisional_exchange_id: str | None = None
    after_broadcast: Callable[[], None] | None = None


@dataclass(frozen=True)
class _PauseOutcome:
    pf: bp.PausedFlow
    final_ir: InternalRequest | None = None
    mutated_manually: bool = False
    audit: OverrideAudit | None = None
    release_payload: bytes | None = None


def resolve_paused_flow(
    pf: bp.PausedFlow,
) -> tuple[InternalRequest, bool, OverrideAudit | None]:
    """Decide the IR to forward, mutation flag, and audit to persist.

    A release via the Forward button populates ``pf.mutated_ir``, but that
    alone does not imply the user changed anything: the editor may have been
    opened and submitted unchanged. Declare manual mutation only when the
    submitted IR structurally diverges from the pipeline's ``curated_ir``.

    The audit returned tracks the paused flow's ``pf.audit`` and not the
    pre-pause snapshot captured by ``run_pipeline``. That pre-pause audit
    is stale as soon as the user touches the overrides panel. Persisting
    the stale audit makes the Inspect tab fall back to structural diff and
    re-exposes the pop-cascade bug. Return None when the user manually
    edited the textareas, because ``pf.audit`` describes ``pf.curated_ir``
    but the final IR is ``pf.mutated_ir``.
    """
    if pf.mutated_ir is None:
        return pf.curated_ir, False, pf.audit
    mutated = pf.mutated_ir != pf.curated_ir
    audit = None if mutated else pf.audit
    return pf.mutated_ir, mutated, audit


def _release_payload(
    pf: bp.PausedFlow,
    adapter: Any,  # Any: adapter protocol has no shared base
    final_ir: InternalRequest,
) -> bytes | None:
    """Bytes to forward on release, or None to keep the original wire bytes.

    An explicit user payload (Forward with edits) is always honored. Otherwise
    the request is reserialized only when the released IR diverges from the
    original; an unchanged release leaves mitmproxy's captured bytes intact.
    """
    if pf.release_payload is not None:
        return pf.release_payload
    return outbound_request_if_changed(adapter, pf.original_ir, final_ir)


_pause_count_tasks: set[asyncio.Task[None]] = set()
_PAUSE_DRAIN_TIMEOUT_S = 5.0


def _retire_pause_count_task(task: asyncio.Task[None]) -> None:
    _pause_count_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("pause-count task failed", exc_info=task.exception())


async def drain_pause_count_tasks() -> None:
    """Await in-flight pause-count tasks before shared deps are torn down.

    Pause-count tasks use the token counter's shared HTTP client, so
    ``close_runtime`` drains them before that client is closed
    (littleorgans/python storage Rule 4, no orphan tasks).
    """
    if not _pause_count_tasks:
        return
    _done, pending = await asyncio.wait(list(_pause_count_tasks), timeout=_PAUSE_DRAIN_TIMEOUT_S)
    for task in pending:
        task.cancel()
    # Await cancellation to settle so no task touches the shared HTTP client
    # between cancel() and the client's aclose() in close_runtime (Rule 4).
    await asyncio.gather(*pending, return_exceptions=True)


async def fire_pause_count(
    flow_id: str,
    counter: TokenCountingClient,
    payload: bytes,
    auth: dict[str, str],
) -> None:
    """Count tokens for a paused flow and announce the result on the bus.

    Runs fire and forget so the initial ``paused`` event reaches the UI
    immediately. A follow-up ``paused_tokens`` event carries the real count
    once the Anthropic round-trip completes. On failure no event is emitted
    and the UI keeps its unset token state.
    """
    try:
        tokens = await counter.count(payload, auth)
    except Exception:
        logger.exception("count_tokens failed at breakpoint %s", flow_id)
        return
    if tokens is None:
        return
    if not await bp.set_tokens_before(flow_id, tokens):
        return
    broadcast.emit(
        {
            "type": "paused_tokens",
            "flow_id": flow_id,
            "tokens_before": tokens,
        }
    )


def _paused_event_payload(
    *,
    flow_id: str,
    transport: str,
    original_ir: InternalRequest,
    curated_ir: InternalRequest,
    audit: OverrideAudit | None,
    paused_at_ms: int,
    provisional_exchange_id: str | None = None,
    run_id: str | None = None,
    track_id: str | None = None,
    parent_track_id: str | None = None,
    track_display_name: str | None = None,
    track_role: Literal["parent", "subagent"] | None = None,
    spawn_anchor: SpawnAnchor | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "paused",
        "flow_id": flow_id,
        "transport": transport,
        "ir": curated_ir.model_dump(mode="json"),
        "original_tools": [t.model_dump(mode="json") for t in original_ir.tools],
        "original_system": [sp.model_dump(mode="json") for sp in original_ir.system],
        "original_messages": [m.model_dump(mode="json") for m in original_ir.messages],
        "original_sampling": original_ir.sampling.model_dump(mode="json"),
        "original_provider_extras": dict(original_ir.provider_extras),
        "audit": audit.model_dump(mode="json") if audit else None,
        "paused_at_ms": paused_at_ms,
        "tokens_before": None,
        "run_id": run_id,
        "track_id": track_id,
        "parent_track_id": parent_track_id,
        "track_display_name": track_display_name,
        "track_role": track_role,
        "spawn_anchor": spawn_anchor.model_dump(mode="json") if spawn_anchor is not None else None,
    }
    if provisional_exchange_id is not None:
        payload["provisional_exchange_id"] = provisional_exchange_id
    return payload


def _flow_track_fields(flow: http.HTTPFlow) -> TrackFields:
    request_state = get_request_flow_state(flow)
    assignment = request_state.track_assignment if request_state is not None else None
    return {
        "run_id": get_settings().run_id,
        "track_id": assignment.track_id if assignment is not None else None,
        "parent_track_id": assignment.parent_track_id if assignment is not None else None,
        "track_display_name": (assignment.track_display_name if assignment is not None else None),
        "track_role": assignment.track_role if assignment is not None else None,
        "spawn_anchor": assignment.spawn_anchor if assignment is not None else None,
    }


async def _run_pause(
    *,
    flow: http.HTTPFlow,
    adapter: Any,  # Any: adapter protocol has no shared base
    original_ir: InternalRequest,
    curated_ir: InternalRequest,
    audit: OverrideAudit | None,
    transport: Literal["http", "websocket"],
    log_label: str,
    timeout_label: str,
    prepare_pause: Callable[[], _PauseHooks] | None = None,
) -> _PauseOutcome | None:
    logger.info("%s %s waiting for serializer", log_label, flow.id)
    async with bp.pause_serializer():
        logger.info("%s %s acquired serializer, pausing", log_label, flow.id)
        hooks = prepare_pause() if prepare_pause is not None else _PauseHooks()
        paused_at_ms = int(time.time() * 1000)
        track_fields = _flow_track_fields(flow)
        event = await bp.pause(
            flow,
            original_ir,
            curated_ir,
            transport=transport,
            audit=audit,
            auth_headers=hooks.auth_headers,
            **track_fields,
        )
        broadcast.emit(
            _paused_event_payload(
                flow_id=flow.id,
                transport=transport,
                original_ir=original_ir,
                curated_ir=curated_ir,
                audit=audit,
                paused_at_ms=paused_at_ms,
                provisional_exchange_id=hooks.provisional_exchange_id,
                **track_fields,
            )
        )
        if hooks.after_broadcast is not None:
            hooks.after_broadcast()
        settings = get_settings()
        try:
            await asyncio.wait_for(event.wait(), timeout=settings.breakpoint_timeout_s)
        except TimeoutError:
            logger.warning(
                "%s (%.0fs) for flow %s, auto-releasing",
                timeout_label,
                settings.breakpoint_timeout_s,
                flow.id,
            )

        pf = await bp.pop_paused(flow.id)
    if pf is None:
        return None
    if pf.dropped:
        return _PauseOutcome(pf=pf)

    final_ir, mutated_manually, final_audit = resolve_paused_flow(pf)
    release_payload = _release_payload(pf, adapter, final_ir)
    return _PauseOutcome(
        pf=pf,
        final_ir=final_ir,
        mutated_manually=mutated_manually,
        audit=final_audit,
        release_payload=release_payload,
    )


async def handle_breakpoint(
    flow: http.HTTPFlow,
    adapter: Any,  # Any: adapter protocol has no shared base
    original_ir: InternalRequest,
    curated_ir: InternalRequest,
    audit: OverrideAudit | None,
    counter: TokenCountingClient | None,
) -> None:
    """Pause at breakpoint, await user action, rewrite request in place."""
    from mitmproxy.http import Response as MitmResponse

    def prepare_http_pause() -> _PauseHooks:
        auth = relevant_auth_headers(flow.request.headers)

        if counter is None:
            return _PauseHooks(auth_headers=auth)

        def after_broadcast() -> None:
            task = asyncio.create_task(
                fire_pause_count(
                    flow.id,
                    counter,
                    adapter.outbound_request(curated_ir),
                    auth,
                ),
                name=f"pause-count:{flow.id}",
            )
            _pause_count_tasks.add(task)
            task.add_done_callback(_retire_pause_count_task)

        return _PauseHooks(auth_headers=auth, after_broadcast=after_broadcast)

    outcome = await _run_pause(
        flow=flow,
        adapter=adapter,
        original_ir=original_ir,
        curated_ir=curated_ir,
        audit=audit,
        transport="http",
        log_label="BREAKPOINT",
        timeout_label="Breakpoint timeout",
        prepare_pause=prepare_http_pause,
    )
    if outcome is None:
        return

    if outcome.pf.dropped:
        update_request_flow_state(flow, dropped=True)
        flow.response = MitmResponse.make(
            400,
            b'{"error": "dropped by user"}',
            {"content-type": "application/json"},
        )
        return

    assert outcome.final_ir is not None
    if outcome.release_payload is not None:
        flow.request.set_text(outcome.release_payload.decode())
    update_request_flow_state(
        flow,
        curated_request_ir=outcome.final_ir,
        audit=outcome.audit,
        mutated_manually=outcome.mutated_manually,
    )


async def handle_websocket_breakpoint(
    flow: http.HTTPFlow,
    message: Any,  # Any: mitmproxy websocket message is untyped here
    adapter: Any,  # Any: adapter protocol has no shared base
    original_ir: InternalRequest,
    curated_ir: InternalRequest,
    audit: OverrideAudit | None,
) -> None:
    def prepare_websocket_pause() -> _PauseHooks:
        transport_state = get_codex_transport_state(flow)
        return _PauseHooks(
            provisional_exchange_id=(
                transport_state.provisional_exchange_id if transport_state is not None else None
            )
        )

    outcome = await _run_pause(
        flow=flow,
        adapter=adapter,
        original_ir=original_ir,
        curated_ir=curated_ir,
        audit=audit,
        transport="websocket",
        log_label="CODEX BREAKPOINT",
        timeout_label="Codex breakpoint timeout",
        prepare_pause=prepare_websocket_pause,
    )
    if outcome is None:
        return

    if outcome.pf.dropped:
        clear_codex_breakpoint_lifecycle(flow)
        mark_codex_initial_request_dropped(flow)
        await delete_codex_provisional_exchange(flow)
        message.drop()
        return

    record_codex_breakpoint_release(
        flow,
        paused_at_ms=outcome.pf.paused_at_ms,
        released_at_ms=int(time.time() * 1000),
    )
    assert outcome.final_ir is not None
    if outcome.release_payload is not None:
        message.content = outcome.release_payload
    update_request_flow_state(
        flow,
        curated_request_ir=outcome.final_ir,
        audit=outcome.audit,
        mutated_manually=outcome.mutated_manually,
    )
    await rewrite_codex_provisional_exchange(flow, force_replay=True)
