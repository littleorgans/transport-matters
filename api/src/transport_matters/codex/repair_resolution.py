"""Resolution logic for persisted Codex derived artifacts."""

from transport_matters.codex.derivation_contract import CodexDerivedTurnArtifacts
from transport_matters.codex.repair_models import (
    CodexDerivedArtifactsDiagnostic,
    CodexDerivedArtifactsResolution,
    build_repair_diagnostic,
)
from transport_matters.codex.repair_payloads import (
    _parse_events_jsonl,
    _parse_turn_json,
    _supported_versions,
    _unsupported_versions,
)
from transport_matters.storage.base import CodexDerivedArtifactFiles, ExchangeArtifacts


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
            build_repair_diagnostic(
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
            build_repair_diagnostic(
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
            build_repair_diagnostic(
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
            build_repair_diagnostic(
                "error",
                "codex_derived_incomplete",
                "Persisted Codex derived artifacts are incomplete.",
                detail="Both events.jsonl and turn.json are required.",
            )
        )
    elif not diagnostics:
        diagnostics.append(
            build_repair_diagnostic(
                "error",
                "codex_derived_unreadable",
                "Persisted Codex derived artifacts could not be validated.",
            )
        )

    return CodexDerivedArtifactsResolution(
        status="inconsistent",
        diagnostics=tuple(diagnostics),
    )


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


def _is_codex_exchange(artifacts: ExchangeArtifacts) -> bool:
    if artifacts.request_ir.provider == "codex":
        return True
    transport = artifacts.transport
    return transport is not None and transport.provider == "codex"
