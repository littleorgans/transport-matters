"""Breakpoint pause and release helpers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, cast

from manicure import breakpoint as bp
from manicure import broadcast
from manicure.codex.exchange import _delete_codex_provisional_exchange
from manicure.codex.transport import (
    get_codex_transport_state,
    mark_codex_initial_request_dropped,
)
from manicure.config import get_settings
from manicure.counting import TokenCountingClient, _relevant_auth_headers
from manicure.flow_state import update_request_flow_state

if TYPE_CHECKING:
    from mitmproxy import http

    from manicure.ir import InternalRequest
    from manicure.overrides import OverrideAudit

logger = logging.getLogger(__name__)


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
) -> bytes:
    if pf.release_payload is not None:
        return pf.release_payload
    return cast("bytes", adapter.outbound_request(final_ir))


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
    }
    if provisional_exchange_id is not None:
        payload["provisional_exchange_id"] = provisional_exchange_id
    return payload


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

    logger.info("BREAKPOINT %s waiting for serializer", flow.id)
    async with bp.pause_serializer():
        logger.info("BREAKPOINT %s acquired serializer, pausing", flow.id)
        auth = _relevant_auth_headers(flow.request.headers)
        paused_at_ms = int(time.time() * 1000)
        event = await bp.pause(
            flow,
            original_ir,
            curated_ir,
            transport="http",
            audit=audit,
            auth_headers=auth,
        )
        broadcast.emit(
            _paused_event_payload(
                flow_id=flow.id,
                transport="http",
                original_ir=original_ir,
                curated_ir=curated_ir,
                audit=audit,
                paused_at_ms=paused_at_ms,
            )
        )
        if counter is not None:
            asyncio.create_task(
                fire_pause_count(
                    flow.id,
                    counter,
                    adapter.outbound_request(curated_ir),
                    auth,
                )
            )
        settings = get_settings()
        try:
            await asyncio.wait_for(event.wait(), timeout=settings.breakpoint_timeout_s)
        except TimeoutError:
            logger.warning(
                "Breakpoint timeout (%.0fs) for flow %s, auto-releasing",
                settings.breakpoint_timeout_s,
                flow.id,
            )

        pf = await bp.pop_paused(flow.id)
    if pf is None:
        return

    if pf.dropped:
        flow.response = MitmResponse.make(
            400,
            b'{"error": "dropped by user"}',
            {"content-type": "application/json"},
        )
        return

    final_ir, mutated_manually, final_audit = resolve_paused_flow(pf)
    flow.request.set_text(_release_payload(pf, adapter, final_ir).decode())
    update_request_flow_state(
        flow,
        curated_request_ir=final_ir,
        audit=final_audit,
        mutated_manually=mutated_manually,
    )


async def handle_websocket_breakpoint(
    flow: http.HTTPFlow,
    message: Any,  # Any: mitmproxy websocket message is untyped here
    adapter: Any,  # Any: adapter protocol has no shared base
    original_ir: InternalRequest,
    curated_ir: InternalRequest,
    audit: OverrideAudit | None,
) -> None:
    logger.info("CODEX BREAKPOINT %s waiting for serializer", flow.id)
    async with bp.pause_serializer():
        logger.info("CODEX BREAKPOINT %s acquired serializer, pausing", flow.id)
        transport_state = get_codex_transport_state(flow)
        paused_at_ms = int(time.time() * 1000)
        event = await bp.pause(
            flow,
            original_ir,
            curated_ir,
            transport="websocket",
            audit=audit,
        )
        broadcast.emit(
            _paused_event_payload(
                flow_id=flow.id,
                transport="websocket",
                original_ir=original_ir,
                curated_ir=curated_ir,
                audit=audit,
                paused_at_ms=paused_at_ms,
                provisional_exchange_id=(
                    transport_state.provisional_exchange_id
                    if transport_state is not None
                    else None
                ),
            )
        )
        settings = get_settings()
        try:
            await asyncio.wait_for(event.wait(), timeout=settings.breakpoint_timeout_s)
        except TimeoutError:
            logger.warning(
                "Codex breakpoint timeout (%.0fs) for flow %s, auto-releasing",
                settings.breakpoint_timeout_s,
                flow.id,
            )

        pf = await bp.pop_paused(flow.id)
    if pf is None:
        return

    if pf.dropped:
        mark_codex_initial_request_dropped(flow)
        await _delete_codex_provisional_exchange(flow)
        message.drop()
        return

    final_ir, mutated_manually, final_audit = resolve_paused_flow(pf)
    message.content = _release_payload(pf, adapter, final_ir)
    update_request_flow_state(
        flow,
        curated_request_ir=final_ir,
        audit=final_audit,
        mutated_manually=mutated_manually,
    )
