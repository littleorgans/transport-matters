"""Codex transport diagnostics derived from persisted artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters.storage.base import TransportArtifacts, TransportDiagnostic

if TYPE_CHECKING:
    from transport_matters.storage.base import ExchangeArtifacts

_TRUST_ERROR_NEEDLES = (
    "unknownissuer",
    "unknown issuer",
    "certificate verify failed",
    "unable to get local issuer certificate",
    "self signed certificate",
)


def build_codex_transport_diagnostics(
    artifacts: ExchangeArtifacts,
) -> list[TransportDiagnostic]:
    """Return actionable Codex diagnostics for persisted transport artifacts."""
    transport = artifacts.transport
    if transport is None or transport.provider != "codex":
        return []

    diagnostics: list[TransportDiagnostic] = []
    status = transport.upgrade.response_status_code
    response_text = _response_text(artifacts.response_raw)
    response_text_folded = response_text.lower() if response_text else ""

    if status is not None and status != 101:
        if any(needle in response_text_folded for needle in _TRUST_ERROR_NEEDLES):
            diagnostics.append(
                TransportDiagnostic(
                    severity="error",
                    code="proxy_trust_failed",
                    summary="Proxy trust failed before the Codex websocket upgraded.",
                    detail=_status_detail(
                        status,
                        transport,
                        artifacts.response_raw,
                        body_reason="matched a proxy TLS trust failure signature",
                    ),
                    operator_checks=[
                        "Verify the managed Codex process inherited HTTP_PROXY and HTTPS_PROXY for the Transport Matters proxy.",
                        "Verify CODEX_CA_CERTIFICATE points at a readable bundle that includes ~/.mitmproxy/mitmproxy-ca-cert.pem.",
                        "Retry with `transport-matters codex --debug` and compare response.raw with the stored upgrade headers.",
                    ],
                )
            )
        elif status in {401, 403}:
            diagnostics.append(
                TransportDiagnostic(
                    severity="error",
                    code="chatgpt_auth_rejected",
                    summary="ChatGPT rejected the Codex websocket upgrade.",
                    detail=_status_detail(
                        status,
                        transport,
                        artifacts.response_raw,
                        body_reason="status indicates an upstream auth challenge",
                    ),
                    operator_checks=[
                        "Confirm Codex is authenticated with ChatGPT in the environment Transport Matters launched.",
                        "Reproduce with the ChatGPT transport path rather than the API key harness when validating product behavior.",
                        "Inspect response.raw and the upgrade response headers for any upstream auth challenge details.",
                    ],
                )
            )
        else:
            diagnostics.append(
                TransportDiagnostic(
                    severity="error",
                    code="websocket_handshake_failed",
                    summary="The Codex websocket handshake failed before any frames were exchanged.",
                    detail=_status_detail(status, transport, artifacts.response_raw),
                    operator_checks=[
                        "Inspect response.raw for proxy or upstream error text.",
                        "Verify the target path is chatgpt.com/backend-api/codex/responses and the proxy is in explicit mode.",
                        "Retry with `transport-matters codex --debug` if the stored headers are insufficient.",
                    ],
                )
            )

    close = transport.close
    if close is not None:
        abnormal_close = close.close_code not in (None, 1000, 1001)
        if abnormal_close:
            diagnostics.append(
                TransportDiagnostic(
                    severity="warning",
                    code="websocket_closed_abnormally",
                    summary="The Codex websocket closed abnormally after the upgrade completed.",
                    detail=(
                        "close_code="
                        f"{close.close_code} close_reason={close.close_reason or 'none'} "
                        f"client_frames={close.client_message_count} server_frames={close.server_message_count}"
                    ),
                    operator_checks=[
                        "Inspect the final server frames in transport.messages to find the last successful event.",
                        "Correlate close_code with upstream failures before changing the request adapter.",
                        "If server_frames is zero, treat this like a transport issue before assuming an IR bug.",
                    ],
                )
            )
        if not close.initial_client_frame_captured:
            diagnostics.append(
                TransportDiagnostic(
                    severity="error",
                    code="initial_frame_missing",
                    summary="No initial response.create frame was captured for this Codex session.",
                    detail=(
                        "Transport Matters never saw the first client websocket frame, so there is no request IR "
                        "to normalize or edit."
                    ),
                    operator_checks=[
                        "Verify the client actually routed through the Transport Matters proxy for this run.",
                        "If the upgrade failed, inspect the handshake diagnostics before touching adapter code.",
                        "If the upgrade succeeded, inspect proxy logs for websocket framing errors or reconnect loops.",
                    ],
                )
            )
    elif status == 101 and not transport.messages:
        diagnostics.append(
            TransportDiagnostic(
                severity="warning",
                code="no_transport_frames",
                summary="The websocket upgraded but no Codex frames were persisted.",
                detail="The transport record has a successful upgrade and zero captured websocket messages.",
                operator_checks=[
                    "Verify the client sent a response.create frame after the upgrade completed.",
                    "Check for an early reconnect or client exit before the first frame.",
                    "Use `transport-matters codex --debug` if this reproduces consistently.",
                ],
            )
        )

    return diagnostics


def _response_text(raw: bytes | None) -> str | None:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace").strip()
    return text or None


def _status_detail(
    status: int,
    transport: TransportArtifacts,
    response_raw: bytes | None,
    *,
    body_reason: str | None = None,
) -> str:
    parts = [f"upgrade response status={status}"]
    content_type = _response_header_value(transport, "content-type")
    if content_type is not None:
        parts.append(f"content-type={content_type}")
    redaction = _redacted_body_detail(response_raw, body_reason=body_reason)
    if redaction is not None:
        parts.append(redaction)
    return "; ".join(parts)


def _response_header_value(transport: TransportArtifacts, name: str) -> str | None:
    for header in transport.upgrade.response_headers:
        if header.name.lower() == name:
            return header.value
    return None


def _redacted_body_detail(
    response_raw: bytes | None, *, body_reason: str | None = None
) -> str | None:
    if not response_raw:
        return None
    if body_reason is None:
        return f"response body redacted ({len(response_raw)} bytes)"
    return f"response body redacted ({len(response_raw)} bytes; {body_reason})"
