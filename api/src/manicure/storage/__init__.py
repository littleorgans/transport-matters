"""Storage layer exports."""

from manicure.storage.base import (
    ExchangeArtifacts,
    IndexEntry,
    StorageBackend,
)
from manicure.storage.disk import DiskStorageBackend


def get_storage(root: str | None = None) -> StorageBackend:
    """Return the default disk storage backend."""
    if root is not None:
        return DiskStorageBackend(root=root)
    return DiskStorageBackend()


__all__ = [
    "ExchangeArtifacts",
    "IndexEntry",
    "StorageBackend",
    "get_storage",
]
