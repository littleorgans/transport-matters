"""Test-mode mitmproxy addon: force Codex WS→HTTP fallback.

When loaded alongside the production `addon.py`, this addon intercepts
Codex's WebSocket upgrade request and short-circuits it with HTTP 426
(Upgrade Required). Codex CLI treats 426 as the cue to flip
`disable_websockets` immediately, so the very next turn lands on the
HTTPS Responses transport with no retry backoff.

This is a capture aid for validating the HTTP fallback wire format
against real Codex CLI traffic without modifying `~/.codex/config.toml`
or waiting for organic fallback. It is loaded only when the user passes
`--force-http-fallback` to `transport-matters codex`.

Reference: `codex-rs/core/tests/suite/websocket_fallback.rs` —
`websocket_fallback_switches_to_http_on_upgrade_required_connect`
(upstream test that confirms 426 triggers immediate fallback).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mitmproxy import http

_CODEX_RESPONSES_PATH_SUFFIX = "/backend-api/codex/responses"
_INJECTED_BODY = (
    b"Upgrade Required (injected by transport-matters --force-http-fallback)\n"
)


def _is_codex_websocket_upgrade(flow: http.HTTPFlow) -> bool:
    if flow.request.method != "GET":
        return False
    if not flow.request.path.endswith(_CODEX_RESPONSES_PATH_SUFFIX):
        return False
    upgrade = str(flow.request.headers.get("Upgrade", "")).lower()
    return upgrade == "websocket"


class ForceCodexHttpFallback:
    def request(self, flow: http.HTTPFlow) -> None:
        if not _is_codex_websocket_upgrade(flow):
            return
        # Importing inside the hook keeps this addon import-light at load time;
        # mitmproxy.http is only needed when we actually short-circuit.
        from mitmproxy import http

        flow.response = http.Response.make(
            426,
            _INJECTED_BODY,
            {"Content-Type": "text/plain; charset=utf-8"},
        )


addons = [ForceCodexHttpFallback()]
