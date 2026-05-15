"""Redact sensitive transport metadata before it leaves storage."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from transport_matters.storage.base import TransportArtifacts, TransportHeader

_REDACTED_VALUE = "[redacted]"
_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "api-key",
        "apikey",
        "authorization",
        "cookie",
        "proxy-authorization",
        "set-cookie",
        "x-api-key",
    }
)
_SENSITIVE_HEADER_PREFIXES = (
    "cf-access-",
    "openai-sentinel-",
    "x-auth-",
    "x-csrf-",
    "x-openai-",
)


def redact_transport_artifacts(
    transport: TransportArtifacts | None,
) -> tuple[TransportArtifacts | None, bool]:
    """Return a redacted transport artifact plus a "changed" flag."""
    if transport is None:
        return None, False

    updates: dict[str, object] = {}
    upgrade_request, upgrade_request_changed = _redact_headers(
        transport.upgrade.request_headers
    )
    upgrade_response, upgrade_response_changed = _redact_headers(
        transport.upgrade.response_headers
    )
    if upgrade_request_changed or upgrade_response_changed:
        updates["upgrade"] = transport.upgrade.model_copy(
            update={
                "request_headers": upgrade_request,
                "response_headers": upgrade_response,
            }
        )
    if transport.request is not None:
        request_headers, request_changed = _redact_headers(transport.request.headers)
        if request_changed:
            updates["request"] = transport.request.model_copy(
                update={"headers": request_headers}
            )
    if transport.response is not None:
        response_headers, response_changed = _redact_headers(transport.response.headers)
        if response_changed:
            updates["response"] = transport.response.model_copy(
                update={"headers": response_headers}
            )
    if not updates:
        return transport, False

    return transport.model_copy(update=updates), True


def _redact_headers(
    headers: list[TransportHeader],
) -> tuple[list[TransportHeader], bool]:
    redacted: list[TransportHeader] = []
    changed = False
    for header in headers:
        next_header = _redact_header(header)
        redacted.append(next_header)
        if next_header != header:
            changed = True
    return redacted, changed


def _redact_header(header: TransportHeader) -> TransportHeader:
    if not _header_is_sensitive(header.name):
        return header
    return header.model_copy(update={"value": _redact_value(header.name, header.value)})


def _header_is_sensitive(name: str) -> bool:
    lowered = name.strip().lower()
    return (
        lowered in _SENSITIVE_HEADER_NAMES
        or lowered.endswith("-token")
        or lowered.endswith("-session")
        or lowered.startswith(_SENSITIVE_HEADER_PREFIXES)
    )


def _redact_value(name: str, value: str) -> str:
    lowered = name.strip().lower()
    if lowered in {"authorization", "proxy-authorization"}:
        scheme, _, _ = value.partition(" ")
        if scheme:
            return f"{scheme} {_REDACTED_VALUE}"
    return _REDACTED_VALUE
