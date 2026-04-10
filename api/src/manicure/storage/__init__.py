"""Storage layer exports."""

from pathlib import Path

from manicure.storage.base import (
    ExchangeArtifacts,
    IndexEntry,
    PipelineStats,
    ReqStats,
    ResStats,
    RuleAuditEntry,
    StorageBackend,
)
from manicure.storage.disk import DiskStorageBackend

_backend: StorageBackend | None = None


def init_storage(root: Path | None = None) -> StorageBackend:
    """Called once by the addon at startup."""
    global _backend  # noqa: PLW0603
    _backend = DiskStorageBackend(root=root)
    return _backend


def get_storage() -> StorageBackend:
    """FastAPI Depends() target. Lazy-inits with defaults if not yet initialised."""
    global _backend  # noqa: PLW0603
    if _backend is None:
        _backend = DiskStorageBackend()
    return _backend


def reset_storage() -> None:
    """Reset the singleton. Used by tests only."""
    global _backend  # noqa: PLW0603
    _backend = None


__all__ = [
    "ExchangeArtifacts",
    "IndexEntry",
    "PipelineStats",
    "ReqStats",
    "ResStats",
    "RuleAuditEntry",
    "StorageBackend",
    "get_storage",
    "init_storage",
    "reset_storage",
]
