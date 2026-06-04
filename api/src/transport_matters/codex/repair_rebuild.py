"""Rebuild logic for Codex derived artifacts from transport."""

from typing import TYPE_CHECKING, Any

from transport_matters.codex.derivation_contract import (
    CodexDerivationOperatorFact,
    CodexDerivedTurnArtifacts,
    CodexReplayRequest,
    CodexTransportCloseFact,
    CodexTransportMessageFact,
    CodexTurnDerivationContext,
)
from transport_matters.codex.derivation_engine import derive_codex_turn_replay
from transport_matters.codex.protocol import codex_terminal_status, is_codex_turn_start
from transport_matters.codex.repair_models import (
    CodexDerivedArtifactsDiagnostic,
    build_repair_diagnostic,
)
from transport_matters.codex.repair_payloads import (
    coerce_datetime,
    int_field,
    parse_events_jsonl,
    parse_turn_json,
    string_field,
)
from transport_matters.codex.session_metadata import (
    codex_session_id_from_header_lookup,
    codex_session_id_from_request_metadata,
    codex_turn_id_from_header_lookup,
)

if TYPE_CHECKING:
    from datetime import datetime

    from transport_matters.storage.base import CodexDerivedArtifactFiles, ExchangeArtifacts

_OPERATOR_FACT_KINDS = {
    "request_curated",
    "breakpoint_paused",
    "breakpoint_released",
}


def rebuild_codex_derived_artifacts(
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
            build_repair_diagnostic(
                "error",
                "codex_transport_missing",
                "Canonical transport is missing, so Codex derived artifacts cannot be rebuilt.",
            )
        )
        return None, tuple(diagnostics)

    turn_payload, turn_parse_diagnostics = parse_turn_json(derived_files.turn_json)
    diagnostics.extend(turn_parse_diagnostics)
    event_payloads, event_parse_diagnostics = parse_events_jsonl(derived_files.events_jsonl)
    diagnostics.extend(event_parse_diagnostics)

    preferred_start = int_field(turn_payload, "request_message_index")
    request_message_index = _request_message_index(
        transport.messages,
        preferred_start=preferred_start,
    )
    if request_message_index is None:
        diagnostics.append(
            build_repair_diagnostic(
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
                build_repair_diagnostic(
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
            build_repair_diagnostic(
                "error",
                "codex_transport_close_timestamp_missing",
                "The interrupted turn cannot be rebuilt because transport.close.ts is missing.",
            )
        )
        return None, tuple(diagnostics)

    session_id = _session_id(artifacts, turn_payload)
    if session_id is None:
        diagnostics.append(
            build_repair_diagnostic(
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
            turn_index=max(0, int_field(turn_payload, "turn_index") or 0),
            request_message_index=request_message_index,
            model=string_field(turn_payload, "model") or artifacts.request_ir.model,
        ),
        transport_messages=tuple(transport_messages),
        operator_facts=operator_facts,
        close=close,
    )
    rebuilt = derive_codex_turn_replay(replay_request)
    if rebuilt is None:
        diagnostics.append(
            build_repair_diagnostic(
                "info",
                "codex_turn_not_present",
                "Canonical transport does not contain a repairable Codex turn.",
            )
        )
    return rebuilt, tuple(diagnostics)


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
    return string_field(turn_payload, "session_id")


def _turn_id(
    artifacts: ExchangeArtifacts,
    turn_payload: dict[str, Any] | None,
) -> str | None:
    turn_id = string_field(turn_payload, "turn_id")
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
        ts = coerce_datetime(event.get("ts"))
        if ts is None:
            diagnostics.append(
                build_repair_diagnostic(
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
                build_repair_diagnostic(
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
