"""Codex derived artifact resolution, repair, and migration helpers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from transport_matters.codex.derivation_contract import (
    SUPPORTED_CODEX_DERIVATION_VERSIONS,
    CodexDerivationOperatorFact,
    CodexDerivedTurnArtifacts,
    CodexReplayRequest,
    CodexTransportCloseFact,
    CodexTransportMessageFact,
    CodexTurnDerivationContext,
    is_supported_codex_derivation_version,
)
from transport_matters.codex.derivation_engine import derive_codex_turn_replay
from transport_matters.codex.protocol import codex_terminal_status, is_codex_turn_start
from transport_matters.codex.session_metadata import (
    codex_session_id_from_header_lookup,
    codex_session_id_from_request_metadata,
    codex_turn_id_from_header_lookup,
)
from transport_matters.storage.base import (
    CodexDerivedArtifactFiles,
    ExchangeArtifacts,
    StorageBackend,
)

type CodexDerivedArtifactsStatus = Literal[
    "not_applicable",
    "supported",
    "missing",
    "migration_required",
    "inconsistent",
]
type CodexDerivedArtifactsRepairAction = Literal["none", "repaired", "migrated"]

_DATETIME_ADAPTER = TypeAdapter(datetime)
_OPERATOR_FACT_KINDS = {
    "request_curated",
    "breakpoint_paused",
    "breakpoint_released",
}


class CodexDerivedArtifactsDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: Literal["info", "warning", "error"]
    code: str
    summary: str
    detail: str | None = None


class CodexDerivedArtifactsResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: CodexDerivedArtifactsStatus
    derived: CodexDerivedTurnArtifacts | None = None
    diagnostics: tuple[CodexDerivedArtifactsDiagnostic, ...] = Field(default_factory=tuple)


class CodexDerivedArtifactsRepairResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: CodexDerivedArtifactsRepairAction
    status_before: CodexDerivedArtifactsStatus
    derived: CodexDerivedTurnArtifacts | None = None
    diagnostics: tuple[CodexDerivedArtifactsDiagnostic, ...] = Field(default_factory=tuple)


def resolve_codex_derived_artifacts(
    artifacts: ExchangeArtifacts,
    derived_files: CodexDerivedArtifactFiles | None = None,
) -> CodexDerivedArtifactsResolution:
    if not _is_codex_exchange(artifacts):
        return CodexDerivedArtifactsResolution(status="not_applicable")

    diagnostics: list[CodexDerivedArtifactsDiagnostic] = []
    supported, supported_error = _supported_derived_artifacts(artifacts)
    if supported is not None:
        return CodexDerivedArtifactsResolution(status="supported", derived=supported)
    if supported_error is not None:
        diagnostics.append(
            _diagnostic(
                "error",
                "codex_derived_invalid_contract",
                "Persisted Codex derived artifacts are inconsistent.",
                detail=str(supported_error),
            )
        )

    files = derived_files or CodexDerivedArtifactFiles()
    has_events = files.events_jsonl is not None or artifacts.events is not None
    has_turn = files.turn_json is not None or artifacts.turn is not None
    if not has_events and not has_turn:
        diagnostics.append(
            _diagnostic(
                "info",
                "codex_derived_missing",
                "No persisted Codex derived artifacts were found.",
            )
        )
        return CodexDerivedArtifactsResolution(
            status="missing",
            diagnostics=tuple(diagnostics),
        )

    turn_payload, turn_diagnostics = _parse_turn_json(files.turn_json)
    diagnostics.extend(turn_diagnostics)
    event_payloads, event_diagnostics = _parse_events_jsonl(files.events_jsonl)
    diagnostics.extend(event_diagnostics)

    unsupported_versions = _unsupported_versions(turn_payload, event_payloads)
    if unsupported_versions:
        supported_versions = ", ".join(str(value) for value in sorted(_supported_versions()))
        diagnostics.append(
            _diagnostic(
                "warning",
                "codex_derived_migration_required",
                "Persisted Codex derived artifacts use an unsupported derivation version.",
                detail=(
                    "Unsupported versions: "
                    + ", ".join(str(value) for value in unsupported_versions)
                    + f". Supported versions: {supported_versions}"
                ),
            )
        )
        return CodexDerivedArtifactsResolution(
            status="migration_required",
            diagnostics=tuple(diagnostics),
        )

    if has_events != has_turn:
        diagnostics.append(
            _diagnostic(
                "error",
                "codex_derived_incomplete",
                "Persisted Codex derived artifacts are incomplete.",
                detail="Both events.jsonl and turn.json are required.",
            )
        )
    elif not diagnostics:
        diagnostics.append(
            _diagnostic(
                "error",
                "codex_derived_unreadable",
                "Persisted Codex derived artifacts could not be validated.",
            )
        )

    return CodexDerivedArtifactsResolution(
        status="inconsistent",
        diagnostics=tuple(diagnostics),
    )


async def repair_codex_derived_artifacts(
    storage: StorageBackend,
    exchange_id: str,
) -> CodexDerivedArtifactsRepairResult:
    artifacts = await storage.read_exchange(exchange_id)
    derived_files = await storage.read_codex_derived_files(exchange_id)
    resolution = resolve_codex_derived_artifacts(artifacts, derived_files)

    if resolution.status in {"not_applicable", "supported"}:
        return CodexDerivedArtifactsRepairResult(
            action="none",
            status_before=resolution.status,
            derived=resolution.derived,
            diagnostics=resolution.diagnostics,
        )

    rebuilt, rebuild_diagnostics = _rebuild_codex_derived_artifacts(
        exchange_id=exchange_id,
        artifacts=artifacts,
        derived_files=derived_files,
    )
    diagnostics = (*resolution.diagnostics, *rebuild_diagnostics)
    if rebuilt is None:
        return CodexDerivedArtifactsRepairResult(
            action="none",
            status_before=resolution.status,
            diagnostics=diagnostics,
        )

    await storage.write_codex_derived_artifacts(
        exchange_id,
        artifacts.model_copy(update={"events": rebuilt.events, "turn": rebuilt.turn}),
    )
    return CodexDerivedArtifactsRepairResult(
        action=("migrated" if resolution.status == "migration_required" else "repaired"),
        status_before=resolution.status,
        derived=rebuilt,
        diagnostics=diagnostics,
    )


def _rebuild_codex_derived_artifacts(
    *,
    exchange_id: str,
    artifacts: ExchangeArtifacts,
    derived_files: CodexDerivedArtifactFiles,
) -> tuple[
    CodexDerivedTurnArtifacts | None,
    tuple[CodexDerivedArtifactsDiagnostic, ...],
]:
    diagnostics: list[CodexDerivedArtifactsDiagnostic] = []

    transport = artifacts.transport
    if transport is None:
        diagnostics.append(
            _diagnostic(
                "error",
                "codex_transport_missing",
                "Canonical transport is missing, so Codex derived artifacts cannot be rebuilt.",
            )
        )
        return None, tuple(diagnostics)

    turn_payload, turn_parse_diagnostics = _parse_turn_json(derived_files.turn_json)
    diagnostics.extend(turn_parse_diagnostics)
    event_payloads, event_parse_diagnostics = _parse_events_jsonl(derived_files.events_jsonl)
    diagnostics.extend(event_parse_diagnostics)

    preferred_start = _int_field(turn_payload, "request_message_index")
    request_message_index = _request_message_index(
        transport.messages,
        preferred_start=preferred_start,
    )
    if request_message_index is None:
        diagnostics.append(
            _diagnostic(
                "info",
                "codex_turn_not_present",
                "Canonical transport does not contain a Codex turn start frame.",
            )
        )
        return None, tuple(diagnostics)

    transport_messages: list[CodexTransportMessageFact] = []
    for message_index, message in enumerate(
        transport.messages[request_message_index:],
        start=request_message_index,
    ):
        if message.ts is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "codex_transport_message_timestamp_missing",
                    "A transport frame is missing its canonical timestamp.",
                    detail=f"message_index={message_index}",
                )
            )
            return None, tuple(diagnostics)
        transport_messages.append(
            CodexTransportMessageFact(
                message_index=message_index,
                ts=message.ts,
                direction=message.direction,
                event_type=message.event_type,
                payload_json=message.payload_json,
                dropped=message.dropped,
            )
        )

    close = _close_fact(artifacts, transport_messages)
    if close is None and _requires_close_timestamp(artifacts, transport_messages):
        diagnostics.append(
            _diagnostic(
                "error",
                "codex_transport_close_timestamp_missing",
                "The interrupted turn cannot be rebuilt because transport.close.ts is missing.",
            )
        )
        return None, tuple(diagnostics)

    session_id = _session_id(artifacts, turn_payload)
    if session_id is None:
        diagnostics.append(
            _diagnostic(
                "error",
                "codex_session_id_missing",
                "The Codex session_id is missing from canonical request metadata.",
            )
        )
        return None, tuple(diagnostics)

    start_ts = transport_messages[0].ts
    operator_facts, operator_diagnostics = _operator_facts(
        event_payloads,
        default_request_curated_ts=start_ts,
        infer_request_curated=_request_curated_present(artifacts),
    )
    diagnostics.extend(operator_diagnostics)

    replay_request = CodexReplayRequest(
        context=CodexTurnDerivationContext(
            exchange_id=exchange_id,
            session_id=session_id,
            turn_id=_turn_id(artifacts, turn_payload) or exchange_id,
            turn_index=max(0, _int_field(turn_payload, "turn_index") or 0),
            request_message_index=request_message_index,
            model=_string_field(turn_payload, "model") or artifacts.request_ir.model,
        ),
        transport_messages=tuple(transport_messages),
        operator_facts=operator_facts,
        close=close,
    )
    rebuilt = derive_codex_turn_replay(replay_request)
    if rebuilt is None:
        diagnostics.append(
            _diagnostic(
                "info",
                "codex_turn_not_present",
                "Canonical transport does not contain a repairable Codex turn.",
            )
        )
    return rebuilt, tuple(diagnostics)


def _supported_derived_artifacts(
    artifacts: ExchangeArtifacts,
) -> tuple[CodexDerivedTurnArtifacts | None, Exception | None]:
    if artifacts.events is None or artifacts.turn is None:
        return None, None
    try:
        return (
            CodexDerivedTurnArtifacts(events=artifacts.events, turn=artifacts.turn),
            None,
        )
    except Exception as exc:  # pragma: no cover - narrow shape exercised upstream
        return None, exc


def _parse_turn_json(
    payload: bytes | None,
) -> tuple[dict[str, Any] | None, tuple[CodexDerivedArtifactsDiagnostic, ...]]:
    if payload is None:
        return None, ()
    try:
        data = json.loads(payload.decode())
    except UnicodeDecodeError as exc:
        return None, (
            _diagnostic(
                "error",
                "codex_turn_decode_failed",
                "turn.json could not be decoded as UTF-8.",
                detail=str(exc),
            ),
        )
    except json.JSONDecodeError as exc:
        return None, (
            _diagnostic(
                "error",
                "codex_turn_parse_failed",
                "turn.json is not valid JSON.",
                detail=str(exc),
            ),
        )
    if not isinstance(data, dict):
        return None, (
            _diagnostic(
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
            _diagnostic(
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
                _diagnostic(
                    "error",
                    "codex_events_parse_failed",
                    "events.jsonl contains invalid JSON.",
                    detail=f"line {line_number}: {exc}",
                )
            )
            continue
        if not isinstance(data, dict):
            diagnostics.append(
                _diagnostic(
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


def _request_message_index(
    messages: list[Any],
    *,
    preferred_start: int | None,
) -> int | None:
    if (
        preferred_start is not None
        and 0 <= preferred_start < len(messages)
        and _is_turn_start_message(messages[preferred_start])
    ):
        return preferred_start
    for index, message in enumerate(messages):
        if _is_turn_start_message(message):
            return index
    return None


def _is_turn_start_message(message: Any) -> bool:
    if getattr(message, "direction", None) != "client":
        return False
    payload = getattr(message, "payload_json", None)
    return isinstance(payload, dict) and is_codex_turn_start(payload, from_client=True)


def _close_fact(
    artifacts: ExchangeArtifacts,
    transport_messages: list[CodexTransportMessageFact],
) -> CodexTransportCloseFact | None:
    transport_close = artifacts.transport.close if artifacts.transport else None
    if transport_close is None or transport_close.ts is None:
        return None
    if not _requires_close_timestamp(artifacts, transport_messages):
        return None
    return CodexTransportCloseFact(
        ts=transport_close.ts,
        close_code=transport_close.close_code,
        close_reason=transport_close.close_reason,
    )


def _requires_close_timestamp(
    artifacts: ExchangeArtifacts,
    transport_messages: list[CodexTransportMessageFact],
) -> bool:
    if artifacts.transport is None or artifacts.transport.close is None:
        return False
    return not any(
        message.direction == "server"
        and isinstance(message.payload_json, dict)
        and codex_terminal_status(message.payload_json, from_client=False) is not None
        for message in transport_messages
    )


def _session_id(
    artifacts: ExchangeArtifacts,
    turn_payload: dict[str, Any] | None,
) -> str | None:
    session_id = codex_session_id_from_request_metadata(artifacts.request_ir.metadata)
    if session_id is not None:
        return session_id
    request_headers = _transport_request_headers(artifacts)
    if request_headers:
        session_id = codex_session_id_from_header_lookup(
            lambda name: request_headers.get(name.lower())
        )
        if session_id is not None:
            return session_id
    return _string_field(turn_payload, "session_id")


def _turn_id(
    artifacts: ExchangeArtifacts,
    turn_payload: dict[str, Any] | None,
) -> str | None:
    turn_id = _string_field(turn_payload, "turn_id")
    if turn_id is not None:
        return turn_id
    request_headers = _transport_request_headers(artifacts)
    return codex_turn_id_from_header_lookup(lambda name: request_headers.get(name.lower()))


def _transport_request_headers(artifacts: ExchangeArtifacts) -> dict[str, str]:
    transport = artifacts.transport
    if transport is None:
        return {}
    headers = (
        transport.request.headers
        if transport.protocol == "http" and transport.request is not None
        else transport.upgrade.request_headers
    )
    return {header.name.strip().lower(): header.value for header in headers}


def _operator_facts(
    event_payloads: tuple[dict[str, Any], ...],
    *,
    default_request_curated_ts: datetime,
    infer_request_curated: bool,
) -> tuple[
    tuple[CodexDerivationOperatorFact, ...],
    tuple[CodexDerivedArtifactsDiagnostic, ...],
]:
    diagnostics: list[CodexDerivedArtifactsDiagnostic] = []
    facts: dict[str, CodexDerivationOperatorFact] = {}
    for event in event_payloads:
        kind = event.get("kind")
        if kind not in _OPERATOR_FACT_KINDS or kind in facts:
            continue
        ts = _coerce_datetime(event.get("ts"))
        if ts is None:
            diagnostics.append(
                _diagnostic(
                    "warning",
                    "codex_operator_ts_missing",
                    "An operator event in events.jsonl is missing a usable timestamp.",
                    detail=f"kind={kind}",
                )
            )
            continue
        data = event.get("data")
        try:
            facts[kind] = CodexDerivationOperatorFact(
                kind=kind,
                ts=ts,
                data=data if isinstance(data, dict) else {},
            )
        except Exception as exc:
            diagnostics.append(
                _diagnostic(
                    "warning",
                    "codex_operator_event_invalid",
                    "An operator event in events.jsonl could not be reused during migration.",
                    detail=str(exc),
                )
            )
    if infer_request_curated and "request_curated" not in facts:
        facts["request_curated"] = CodexDerivationOperatorFact(
            kind="request_curated",
            ts=default_request_curated_ts,
        )
    return tuple(facts.values()), tuple(diagnostics)


def _request_curated_present(artifacts: ExchangeArtifacts) -> bool:
    # request_curated_raw only proves that re-serialization changed bytes.
    # Codex can persist that artifact for untouched turns, so the semantic
    # repair path only trusts the curated IR snapshot as evidence of a
    # materially changed request.
    return artifacts.request_curated_ir is not None


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


def _is_codex_exchange(artifacts: ExchangeArtifacts) -> bool:
    if artifacts.request_ir.provider == "codex":
        return True
    transport = artifacts.transport
    return transport is not None and transport.provider == "codex"


def _diagnostic(
    severity: Literal["info", "warning", "error"],
    code: str,
    summary: str,
    *,
    detail: str | None = None,
) -> CodexDerivedArtifactsDiagnostic:
    return CodexDerivedArtifactsDiagnostic(
        severity=severity,
        code=code,
        summary=summary,
        detail=detail,
    )


__all__ = [
    "CodexDerivedArtifactsDiagnostic",
    "CodexDerivedArtifactsRepairAction",
    "CodexDerivedArtifactsRepairResult",
    "CodexDerivedArtifactsResolution",
    "CodexDerivedArtifactsStatus",
    "repair_codex_derived_artifacts",
    "resolve_codex_derived_artifacts",
]
