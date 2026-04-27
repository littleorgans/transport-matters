"""Storage layer exports."""

import asyncio
from pathlib import Path

from manicure.storage.base import (
    CodexDerivedArtifactFiles,
    CodexTurnListSummary,
    ExchangeArtifacts,
    IndexEntry,
    OverrideAuditEntry,
    PipelineStats,
    ReqStats,
    ResStats,
    SpawnAnchor,
    StorageBackend,
    TransportArtifacts,
    TransportCloseArtifacts,
    TransportDiagnostic,
    TransportHeader,
    TransportMessageArtifact,
    TransportUpgradeArtifacts,
)
from manicure.storage.disk import DiskStorageBackend

_backend: StorageBackend | None = None
_init_lock: asyncio.Lock = asyncio.Lock()


def init_storage(root: Path | None = None) -> StorageBackend:
    """Called once by the addon at startup."""
    global _backend  # noqa: PLW0603
    _backend = DiskStorageBackend(root=root)
    return _backend


async def get_storage() -> StorageBackend:
    """Lazy-init using settings.storage_dir if not yet initialised.

    Uses double-checked locking to prevent concurrent initialization.
    """
    global _backend  # noqa: PLW0603
    if _backend is not None:
        return _backend
    async with _init_lock:
        if _backend is None:
            from manicure.config import get_settings

            _backend = DiskStorageBackend(root=get_settings().storage_dir)
        return _backend


def reset_storage() -> None:
    """Reset the singleton. Used by tests only."""
    global _backend  # noqa: PLW0603
    _backend = None


__all__ = [
    "ExchangeArtifacts",
    "IndexEntry",
    "OverrideAuditEntry",
    "PipelineStats",
    "ReqStats",
    "ResStats",
    "SpawnAnchor",
    "StorageBackend",
    "TransportArtifacts",
    "TransportCloseArtifacts",
    "TransportDiagnostic",
    "TransportHeader",
    "TransportMessageArtifact",
    "TransportUpgradeArtifacts",
    "get_storage",
    "init_storage",
    "reset_storage",
    "CodexDerivedArtifactFiles",
    "CodexTurnListSummary",
]
