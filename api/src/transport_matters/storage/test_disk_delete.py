from unittest.mock import patch

import pytest

from transport_matters.storage import test_disk as disk_tests
from transport_matters.storage.base import ExchangeArtifacts, IndexEntry
from transport_matters.storage.disk import DiskStorageBackend


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


class TestDeleteExchange:
    async def test_removes_index_row_and_artifacts(self, storage: DiskStorageBackend) -> None:
        exchange_id = "deadbeef-1234"
        await storage.append_index(disk_tests._make_index_entry(exchange_id))
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(request_raw=b"{}", request_ir=disk_tests._make_ir()),
        )

        removed = await storage.delete_exchange(exchange_id)

        assert removed is True
        assert await storage.read_index_entry(exchange_id) is None
        with pytest.raises(FileNotFoundError):
            await storage.read_exchange(exchange_id)

    async def test_returns_false_when_exchange_is_missing(
        self, storage: DiskStorageBackend
    ) -> None:
        assert await storage.delete_exchange("missing-0000") is False

    async def test_rewrite_failure_restores_index_row_and_artifacts(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "deadbeef-rollback"
        entry = disk_tests._make_index_entry(exchange_id)
        artifacts = ExchangeArtifacts(request_raw=b"{}", request_ir=disk_tests._make_ir())
        await storage.append_index(entry)
        await storage.write_exchange(exchange_id, artifacts)

        async def fail_rewrite(_: dict[str, IndexEntry]) -> None:
            raise OSError("index rewrite failed")

        with (
            patch.object(storage, "_rewrite_index", side_effect=fail_rewrite),
            pytest.raises(OSError, match="index rewrite failed"),
        ):
            await storage.delete_exchange(exchange_id)

        restored = await storage.read_index_entry(exchange_id)
        assert restored == entry
        restored_artifacts = await storage.read_exchange(exchange_id)
        assert restored_artifacts.request_raw == artifacts.request_raw

    async def test_rewrite_failure_preserves_cache_order(self, storage: DiskStorageBackend) -> None:
        first = disk_tests._make_index_entry("deadbeef-first")
        middle = disk_tests._make_index_entry("deadbeef-middle")
        last = disk_tests._make_index_entry("deadbeef-last")
        await storage.append_index(first)
        await storage.append_index(middle)
        await storage.append_index(last)

        async def fail_rewrite(_: dict[str, IndexEntry]) -> None:
            raise OSError("index rewrite failed")

        with (
            patch.object(storage, "_rewrite_index", side_effect=fail_rewrite),
            pytest.raises(OSError, match="index rewrite failed"),
        ):
            await storage.delete_exchange(middle.id)

        assert [entry.id for entry in await storage.read_index(limit=10, offset=0)] == [
            first.id,
            middle.id,
            last.id,
        ]
