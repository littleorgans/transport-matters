"""Storage layer exports."""

import asyncio
from typing import TYPE_CHECKING

from transport_matters.storage.base import (
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
    TransportHttpRequestArtifacts,
    TransportHttpResponseArtifacts,
    TransportMessageArtifact,
    TransportUpgradeArtifacts,
)
from transport_matters.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from pathlib import Path

_backend: StorageBackend | None = None
_init_lock: asyncio.Lock = asyncio.Lock()


def init_storage(root: Path | None = None) -> StorageBackend:
    """Called once by the addon at startup."""
    global _backend
    _backend = DiskStorageBackend(root=root)
    return _backend


async def get_storage() -> StorageBackend:
    """Lazy-init using settings.storage_dir if not yet initialised.

    Uses double-checked locking to prevent concurrent initialization.
    """
    global _backend
    if _backend is not None:
        return _backend
    async with _init_lock:
        if _backend is None:
            from transport_matters.config import get_settings

            _backend = DiskStorageBackend(root=get_settings().storage_dir)
        return _backend


def reset_storage() -> None:
    """Reset the singleton. Used by tests only."""
    global _backend
    _backend = None


__all__ = [
    "CodexDerivedArtifactFiles",
    "CodexTurnListSummary",
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
    "TransportHttpRequestArtifacts",
    "TransportHttpResponseArtifacts",
    "TransportMessageArtifact",
    "TransportUpgradeArtifacts",
    "get_storage",
    "init_storage",
    "reset_storage",
]
