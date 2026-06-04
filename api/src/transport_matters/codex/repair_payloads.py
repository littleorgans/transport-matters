"""Payload parsing helpers for Codex derived artifact repair."""

import json
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter

from transport_matters.codex.derivation_contract import (
    SUPPORTED_CODEX_DERIVATION_VERSIONS,
    is_supported_codex_derivation_version,
)
from transport_matters.codex.repair_models import (
    CodexDerivedArtifactsDiagnostic,
    build_repair_diagnostic,
)

_DATETIME_ADAPTER = TypeAdapter(datetime)


def _parse_turn_json(
    payload: bytes | None,
) -> tuple[dict[str, Any] | None, tuple[CodexDerivedArtifactsDiagnostic, ...]]:
    if payload is None:
        return None, ()
    try:
        data = json.loads(payload.decode())
    except UnicodeDecodeError as exc:
        return None, (
            build_repair_diagnostic(
                "error",
                "codex_turn_decode_failed",
                "turn.json could not be decoded as UTF-8.",
                detail=str(exc),
            ),
        )
    except json.JSONDecodeError as exc:
        return None, (
            build_repair_diagnostic(
                "error",
                "codex_turn_parse_failed",
                "turn.json is not valid JSON.",
                detail=str(exc),
            ),
        )
    if not isinstance(data, dict):
        return None, (
            build_repair_diagnostic(
                "error",
                "codex_turn_shape_invalid",
                "turn.json must decode to an object.",
            ),
        )
    return data, ()


def _parse_events_jsonl(
    payload: bytes | None,
) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[CodexDerivedArtifactsDiagnostic, ...],
]:
    if payload is None:
        return (), ()
    try:
        text = payload.decode()
    except UnicodeDecodeError as exc:
        return (), (
            build_repair_diagnostic(
                "error",
                "codex_events_decode_failed",
                "events.jsonl could not be decoded as UTF-8.",
                detail=str(exc),
            ),
        )
    diagnostics: list[CodexDerivedArtifactsDiagnostic] = []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            diagnostics.append(
                build_repair_diagnostic(
                    "error",
                    "codex_events_parse_failed",
                    "events.jsonl contains invalid JSON.",
                    detail=f"line {line_number}: {exc}",
                )
            )
            continue
        if not isinstance(data, dict):
            diagnostics.append(
                build_repair_diagnostic(
                    "error",
                    "codex_events_shape_invalid",
                    "Each events.jsonl row must decode to an object.",
                    detail=f"line {line_number}",
                )
            )
            continue
        events.append(data)
    return tuple(events), tuple(diagnostics)


def _unsupported_versions(
    turn_payload: dict[str, Any] | None,
    event_payloads: tuple[dict[str, Any], ...],
) -> tuple[int, ...]:
    versions: set[int] = set()
    turn_version = _int_field(turn_payload, "derivation_version")
    if turn_version is not None and not is_supported_codex_derivation_version(turn_version):
        versions.add(turn_version)
    for event in event_payloads:
        event_version = _int_field(event, "derivation_version")
        if event_version is not None and not is_supported_codex_derivation_version(event_version):
            versions.add(event_version)
    return tuple(sorted(versions))


def _coerce_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        return _DATETIME_ADAPTER.validate_python(value)
    except Exception:
        return None


def _string_field(payload: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _int_field(payload: dict[str, Any] | None, key: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _supported_versions() -> frozenset[int]:
    return SUPPORTED_CODEX_DERIVATION_VERSIONS
