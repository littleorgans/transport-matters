"""Service entrypoint for Codex derived artifact repair."""

from typing import TYPE_CHECKING

from transport_matters.codex.repair_models import CodexDerivedArtifactsRepairResult
from transport_matters.codex.repair_rebuild import rebuild_codex_derived_artifacts
from transport_matters.codex.repair_resolution import resolve_codex_derived_artifacts

if TYPE_CHECKING:
    from transport_matters.storage.base import StorageBackend


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

    rebuilt, rebuild_diagnostics = rebuild_codex_derived_artifacts(
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
