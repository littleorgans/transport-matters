"""Data models for Codex derived artifact repair."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from transport_matters.codex.derivation_contract import CodexDerivedTurnArtifacts

type CodexDerivedArtifactsStatus = Literal[
    "not_applicable",
    "supported",
    "missing",
    "migration_required",
    "inconsistent",
]
type CodexDerivedArtifactsRepairAction = Literal["none", "repaired", "migrated"]


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


def build_repair_diagnostic(
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
]
