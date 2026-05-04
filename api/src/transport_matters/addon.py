"""mitmproxy addon for Transport Matters.

Captures /v1/messages exchanges, applies pipeline rules, stores
artifacts, and emits SSE events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any  # Any: mitmproxy loader type is untyped

if TYPE_CHECKING:
    from mitmproxy import http
from transport_matters.addon_handlers import (
    handle_codex_websocket_end,
    handle_codex_websocket_message,
    handle_http_request,
    handle_response,
    log_websocket_start,
)
from transport_matters.addon_runtime import AddonRuntime, close_runtime, load_runtime
from transport_matters.codex.transport import is_codex_websocket_flow
from transport_matters.exchange_recorder import (
    _delete_http_provisional_exchange,
    emit_exchange,
)
from transport_matters.exchange_stats import (
    build_pipeline_stats,
    build_req_stats,
    build_res_stats,
    stamp_pipeline_tokens,
)
from transport_matters.flow_state import get_request_flow_state
from transport_matters.pause_session import (
    fire_pause_count,
    resolve_paused_flow,
)

__all__ = [
    "TransportMattersAddon",
    "build_pipeline_stats",
    "build_req_stats",
    "build_res_stats",
    "emit_exchange",
    "fire_pause_count",
    "resolve_paused_flow",
    "stamp_pipeline_tokens",
    "addons",
]

# ── Addon ───────────────────────────────────────────────────────────


class TransportMattersAddon:
    def __init__(self) -> None:
        self._runtime: AddonRuntime | None = None

    def load(self, loader: Any) -> None:  # Any: mitmproxy loader
        self._runtime = load_runtime()

    async def request(self, flow: http.HTTPFlow) -> None:
        await handle_http_request(
            flow,
            self._runtime.token_counter if self._runtime is not None else None,
        )

    async def done(self) -> None:
        await close_runtime(self._runtime)
        self._runtime = None

    def websocket_start(self, flow: http.HTTPFlow) -> None:
        log_websocket_start(flow)

    async def websocket_message(self, flow: http.HTTPFlow) -> None:
        await handle_codex_websocket_message(flow)

    async def websocket_end(self, flow: http.HTTPFlow) -> None:
        await handle_codex_websocket_end(flow)

    async def response(self, flow: http.HTTPFlow) -> None:
        await handle_response(
            flow,
            self._runtime.token_counter if self._runtime is not None else None,
        )

    async def error(self, flow: http.HTTPFlow) -> None:
        if is_codex_websocket_flow(flow):
            return
        request_state = get_request_flow_state(flow)
        if request_state is None or request_state.provisional_exchange_id is None:
            return
        await _delete_http_provisional_exchange(flow, request_state)


addons = [TransportMattersAddon()]
