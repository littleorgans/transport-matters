"""Addon request and transport orchestration helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from transport_matters import breakpoint as bp
from transport_matters.adapters import get_adapter
from transport_matters.codex.exchange import (
    delete_codex_provisional_exchange,
    finalize_codex_provisional_exchange,
    persist_codex_handshake_failure,
    persist_codex_provisional_exchange,
    persist_unparsed_codex_exchange,
)
from transport_matters.codex.exchange_derivation import (
    clear_codex_breakpoint_lifecycle,
    rewrite_codex_provisional_exchange,
)
from transport_matters.codex.transport import (
    close_codex_transport,
    ensure_codex_transport_state,
    is_codex_http_responses_flow,
    is_codex_turn_terminal_message,
    is_codex_websocket_flow,
    record_codex_websocket_message,
)
from transport_matters.config import get_settings
from transport_matters.counting import (
    TokenCountingClient,
    relevant_auth_headers,
    set_recent_auth,
)
from transport_matters.exchange_recorder import (
    persist_http_exchange,
    persist_http_provisional_exchange,
    persist_unparsed_http_exchange,
)
from transport_matters.flow_state import (
    capture_request_flow_state,
    clear_request_flow_state,
    get_request_flow_state,
    snapshot_codex_http_request_headers,
    update_request_flow_state,
)
from transport_matters.pause_session import (
    handle_breakpoint,
    handle_websocket_breakpoint,
)
from transport_matters.request_diff import outbound_request_if_changed
from transport_matters.request_pipeline import (
    capture_codex_initial_request_ir,
    parse_request_ir,
    run_pipeline,
)

if TYPE_CHECKING:
    from mitmproxy import http

    from transport_matters.shared_proxy import ProxyRunBinding

logger = logging.getLogger(__name__)


def _should_skip_breakpoint(model: str, binding: ProxyRunBinding | None = None) -> bool:
    if binding is not None:
        return any(s in model for s in binding.breakpoint_skip_models)
    settings = get_settings()
    return any(s in model for s in settings.breakpoint_skip_models)


async def handle_http_request(
    flow: http.HTTPFlow,
    token_counter: TokenCountingClient | None,
    binding: ProxyRunBinding | None = None,
) -> None:
    codex_http = is_codex_http_responses_flow(flow)
    if not flow.request.path.startswith("/v1/messages") and not codex_http:
        return
    try:
        adapter = get_adapter(flow)
    except Exception:
        logger.debug("No adapter matches flow %s, passing through", flow.id)
        return

    set_recent_auth(relevant_auth_headers(flow.request.headers), binding=binding)
    result = await parse_request_ir(flow, adapter)
    if result is None:
        await persist_unparsed_http_exchange(flow, adapter, codex_http, binding)
        return
    raw, ir = result

    logger.info(
        "REQ %s model=%s system=%d tools=%d msgs=%d",
        flow.id,
        ir.model,
        len(ir.system),
        len(ir.tools),
        len(ir.messages),
    )

    run_id = binding.run_id if binding is not None else get_settings().run_id
    curated_ir, audit, track_assignment = await run_pipeline(ir, flow.id, run_id)
    request_state = capture_request_flow_state(
        flow,
        adapter=adapter,
        request_ir=ir,
        raw_request=raw,
        curated_request_ir=curated_ir,
        audit=audit,
        run_id=run_id,
        listen_port=binding.listen_port if binding is not None else None,
        track_assignment=track_assignment,
        codex_request_headers=(
            snapshot_codex_http_request_headers(flow.request.headers) if codex_http else None
        ),
    )
    provisional_exchange_id = await persist_http_provisional_exchange(
        flow,
        request_state,
        binding,
    )
    if provisional_exchange_id is not None:
        update_request_flow_state(
            flow,
            provisional_exchange_id=provisional_exchange_id,
        )

    if _should_skip_breakpoint(ir.model, binding):
        logger.info(
            "Breakpoint skip: %s matches breakpoint_skip_models filter",
            flow.id,
        )
    if not _should_skip_breakpoint(ir.model, binding) and bp.is_armed():
        logger.info("BREAKPOINT %s armed, pausing", flow.id)
        await handle_breakpoint(flow, adapter, ir, curated_ir, audit, token_counter)
        return

    logger.debug(
        "Skipping breakpoint for %s (another flow paused or not armed)",
        flow.id,
    )
    outbound = outbound_request_if_changed(adapter, ir, curated_ir)
    if outbound is not None:
        flow.request.set_text(outbound.decode())


def log_websocket_start(flow: http.HTTPFlow) -> None:
    state = ensure_codex_transport_state(flow)
    if state is None:
        return
    logger.info(
        "CODEX WS START %s host=%s path=%s status=%s",
        flow.id,
        state.upgrade.host,
        state.upgrade.path,
        state.upgrade.response_status_code,
    )


async def handle_codex_websocket_message(
    flow: http.HTTPFlow,
    binding: ProxyRunBinding | None = None,
) -> None:
    update = record_codex_websocket_message(flow)
    if update is None:
        return
    state, message, captured_initial = update
    if state.provisional_exchange_id is not None and is_codex_turn_terminal_message(message):
        finalized = await finalize_codex_provisional_exchange(flow, None, binding)
        if not finalized:
            logger.warning(
                "Failed to finalize provisional Codex exchange on terminal server frame for %s",
                flow.id,
            )
        return
    if (
        state.provisional_exchange_id is not None
        and not captured_initial
        and not message.from_client
    ):
        rewritten = await rewrite_codex_provisional_exchange(flow, binding=binding)
        if not rewritten:
            logger.warning(
                "Failed to rewrite provisional Codex exchange during live server advance for %s",
                flow.id,
            )
    if not captured_initial:
        return
    websocket = getattr(flow, "websocket", None)
    if websocket is None:
        return
    turn_start_index = len(websocket.messages) - 1
    if state.provisional_exchange_id is not None:
        finalized = await finalize_codex_provisional_exchange(
            flow,
            None,
            binding,
            message_end=turn_start_index,
        )
        if not finalized:
            logger.warning(
                "Failed to finalize prior provisional Codex exchange before rotating turn for %s",
                flow.id,
            )
    clear_codex_breakpoint_lifecycle(flow)
    state.finalized_exchange_id = None
    state.turn_start_message_index = turn_start_index
    state.turn_client_messages_before = max(0, state.client_message_count - 1)
    state.turn_server_messages_before = state.server_message_count
    ir = capture_codex_initial_request_ir(
        flow,
        state.initial_client_frame or b"",
    )
    if ir is None:
        await persist_unparsed_codex_exchange(flow, state.initial_client_frame or b"", binding)
        clear_request_flow_state(flow)
        return
    request_state = get_request_flow_state(flow)
    if request_state is None:
        return
    state.provisional_exchange_id = None
    adapter = request_state.adapter
    run_id = binding.run_id if binding is not None else get_settings().run_id
    curated_ir, audit, track_assignment = await run_pipeline(ir, flow.id, run_id)
    update_request_flow_state(
        flow,
        curated_request_ir=curated_ir,
        audit=audit,
        track_assignment=track_assignment,
    )
    await persist_codex_provisional_exchange(flow, binding)
    level = logging.INFO if message.is_text else logging.WARNING
    kind = "text" if message.is_text else "binary"
    logger.log(
        level,
        "CODEX WS INIT %s captured initial client %s frame bytes=%d model=%s msgs=%d tools=%d",
        flow.id,
        kind,
        len(state.initial_client_frame or b""),
        ir.model,
        len(ir.messages),
        len(ir.tools),
    )
    if _should_skip_breakpoint(ir.model, binding):
        logger.info(
            "Codex breakpoint skip: %s matches breakpoint_skip_models filter",
            flow.id,
        )
    if not _should_skip_breakpoint(ir.model, binding) and bp.is_armed():
        logger.info("CODEX BREAKPOINT %s armed, pausing", flow.id)
        await handle_websocket_breakpoint(flow, message, adapter, ir, curated_ir, audit)
        return
    outbound = outbound_request_if_changed(adapter, ir, curated_ir)
    if outbound is not None:
        message.content = outbound


async def handle_codex_websocket_end(
    flow: http.HTTPFlow,
    binding: ProxyRunBinding | None = None,
) -> None:
    summary = close_codex_transport(flow)
    if summary is None:
        return
    closer = (
        "client"
        if summary.closed_by_client is True
        else "server"
        if summary.closed_by_client is False
        else "unknown"
    )
    if not summary.initial_client_frame_captured:
        logger.warning(
            "CODEX WS END %s close_code=%s closer=%s initial client frame missing",
            flow.id,
            summary.close_code,
            closer,
        )
        return
    if summary.initial_client_frame_dropped:
        await delete_codex_provisional_exchange(flow, binding)
        logger.info(
            "CODEX WS END %s close_code=%s closer=%s initial client frame dropped; skipping exchange persistence",
            flow.id,
            summary.close_code,
            closer,
        )
        return
    log = logger.info if summary.is_normal else logger.warning
    log(
        "CODEX WS END %s close_code=%s closer=%s client_msgs=%d server_msgs=%d reason=%s",
        flow.id,
        summary.close_code,
        closer,
        summary.client_message_count,
        summary.server_message_count,
        summary.close_reason or "",
    )
    await finalize_codex_provisional_exchange(flow, summary, binding)


async def handle_response(
    flow: http.HTTPFlow,
    token_counter: TokenCountingClient | None,
    binding: ProxyRunBinding | None = None,
) -> None:
    if is_codex_http_responses_flow(flow):
        request_state = get_request_flow_state(flow)
        if request_state is None:
            return
        await persist_http_exchange(flow, request_state, token_counter, binding)
        return
    if is_codex_websocket_flow(flow) and getattr(flow, "websocket", None) is None:
        await persist_codex_handshake_failure(flow, binding)
        return

    request_state = get_request_flow_state(flow)
    if request_state is None:
        return
    await persist_http_exchange(flow, request_state, token_counter, binding)
