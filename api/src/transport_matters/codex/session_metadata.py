"""Helpers for extracting Codex session metadata from request artifacts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from transport_matters.ir import RequestMetadata

_REDACTED_VALUE = "[redacted]"


def codex_session_id_from_request_metadata(metadata: RequestMetadata) -> str | None:
    session_id = _usable_string(metadata.session_id)
    if session_id is not None:
        return session_id
    return codex_session_id_from_provider_metadata(metadata.provider_metadata)


def codex_session_id_from_provider_metadata(
    provider_metadata: object,
) -> str | None:
    if not isinstance(provider_metadata, dict):
        return None

    direct = _string_value(provider_metadata, "session_id", "sessionId")
    if direct is not None:
        return direct

    return _session_id_from_turn_metadata(
        provider_metadata.get("x-codex-turn-metadata")
    )


def codex_session_id_from_header_lookup(
    get_header: Callable[[str], object | None],
) -> str | None:
    for name in ("x-codex-session", "session_id"):
        value = _usable_string(get_header(name))
        if value is not None:
            return value

    return _session_id_from_turn_metadata(get_header("x-codex-turn-metadata"))


def _session_id_from_turn_metadata(raw: object) -> str | None:
    payload = _turn_metadata_payload(raw)
    if payload is None:
        return None
    return _string_value(payload, "session_id", "sessionId")


def _turn_metadata_payload(raw: object) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _string_value(payload: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = _usable_string(payload.get(name))
        if value is not None:
            return value
    return None


def _usable_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if not value or value.strip() == _REDACTED_VALUE:
        return None
    return value


__all__ = [
    "codex_session_id_from_header_lookup",
    "codex_session_id_from_provider_metadata",
    "codex_session_id_from_request_metadata",
]
