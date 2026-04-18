from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

import pytest

from manicure.ir import InternalResponse, TextBlock, UsageStats
from manicure.storage import test_disk as disk_tests
from manicure.storage.base import ExchangeArtifacts, IndexEntry, ResStats

if TYPE_CHECKING:
    from manicure.storage.disk import DiskStorageBackend


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    from manicure.storage.disk import DiskStorageBackend

    return DiskStorageBackend(root=str(tmp_path))


class TestAtomicPersist:
    async def test_new_exchange_rollback_on_index_rewrite_failure(
        self, storage: DiskStorageBackend
    ) -> None:
        entry = disk_tests._make_index_entry("persist-new-001")
        artifacts = ExchangeArtifacts(
            request_raw=b"{}",
            request_ir=disk_tests._make_ir(),
        )

        async def fail_rewrite(_: dict[str, IndexEntry]) -> None:
            raise OSError("index rewrite failed")

        with (
            patch.object(storage, "_rewrite_index", side_effect=fail_rewrite),
            pytest.raises(OSError, match="index rewrite failed"),
        ):
            await storage.persist_exchange(entry, artifacts)

        assert await storage.read_index(limit=10, offset=0) == []
        with pytest.raises(FileNotFoundError):
            await storage.read_exchange(entry.id)
        assert not any(
            path.name.endswith((".tmp", ".bak")) for path in storage.root.iterdir()
        )

    async def test_existing_exchange_restored_on_index_rewrite_failure(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "persist-old-001"
        original_entry = disk_tests._make_index_entry(exchange_id)
        original_artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"original","max_tokens":1024}',
            request_ir=disk_tests._make_ir(),
        )
        await storage.append_index(original_entry)
        await storage.write_exchange(exchange_id, original_artifacts)
        original_dir = storage._find_exchange_dir(exchange_id)

        updated_entry = original_entry.model_copy(
            update={"res": ResStats(stop_reason="completed", text_chars=4)}
        )
        updated_artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"updated","max_tokens":2048}',
            request_ir=disk_tests._make_ir(),
            response_raw=b'{"id":"msg_final"}',
            response_ir=InternalResponse(
                id="msg_final",
                model="anthropic/claude-sonnet-4-20250514",
                provider="anthropic",
                stop_reason="end_turn",
                usage=UsageStats(input_tokens=1, output_tokens=2),
                content=[TextBlock(text="done")],
            ),
        )

        async def fail_rewrite(_: dict[str, IndexEntry]) -> None:
            raise OSError("index rewrite failed")

        with (
            patch.object(storage, "_rewrite_index", side_effect=fail_rewrite),
            pytest.raises(OSError, match="index rewrite failed"),
        ):
            await storage.persist_exchange(updated_entry, updated_artifacts)

        entry = await storage.read_index_entry(exchange_id)
        assert entry == original_entry
        restored_dir = storage._find_exchange_dir(exchange_id)
        assert restored_dir == original_dir
        restored_artifacts = await storage.read_exchange(exchange_id)
        assert restored_artifacts.request_raw == original_artifacts.request_raw
        assert restored_artifacts.response_ir is None
        assert not any(
            path.name.endswith((".tmp", ".bak")) for path in storage.root.iterdir()
        )

    async def test_existing_exchange_persist_uses_non_default_executor(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "persist-old-002"
        original_entry = disk_tests._make_index_entry(exchange_id)
        original_artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"original","max_tokens":1024}',
            request_ir=disk_tests._make_ir(),
        )
        await storage.append_index(original_entry)
        await storage.write_exchange(exchange_id, original_artifacts)

        updated_entry = original_entry.model_copy(
            update={"res": ResStats(stop_reason="completed", text_chars=4)}
        )
        updated_artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"updated","max_tokens":2048}',
            request_ir=disk_tests._make_ir(),
            response_raw=b'{"id":"msg_final"}',
            response_ir=InternalResponse(
                id="msg_final",
                model="anthropic/claude-sonnet-4-20250514",
                provider="anthropic",
                stop_reason="end_turn",
                usage=UsageStats(input_tokens=1, output_tokens=2),
                content=[TextBlock(text="done")],
            ),
        )
        loop = asyncio.get_running_loop()
        original_run_in_executor = loop.run_in_executor

        async def fail_default_executor(
            executor: object,
            func: object,
            *args: object,
        ) -> object:
            if executor is None:
                raise RuntimeError("Executor shutdown has been called")
            return await original_run_in_executor(
                cast("Any", executor),
                cast("Any", func),
                *args,
            )

        with patch.object(loop, "run_in_executor", side_effect=fail_default_executor):
            await storage.persist_exchange(updated_entry, updated_artifacts)

        entry = await storage.read_index_entry(exchange_id)
        assert entry == updated_entry
        restored_artifacts = await storage.read_exchange(exchange_id)
        assert restored_artifacts.request_raw == updated_artifacts.request_raw
        assert restored_artifacts.response_ir == updated_artifacts.response_ir
