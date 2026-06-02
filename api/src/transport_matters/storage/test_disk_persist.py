import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import patch

import pytest

from transport_matters.ir import InternalResponse, TextBlock, UsageStats
from transport_matters.storage import test_disk as disk_tests
from transport_matters.storage.base import ExchangeArtifacts, IndexEntry, ResStats
from transport_matters.storage.disk import DiskStorageBackend
from transport_matters.storage.disk_layout import DiskStorageLayout


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


class TestAtomicPersist:
    async def test_new_exchange_rollback_on_derived_turn_write_failure(
        self, storage: DiskStorageBackend
    ) -> None:
        entry = disk_tests._make_index_entry("persist-derived-001")
        artifacts = ExchangeArtifacts(
            request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
            request_ir=disk_tests._make_ir(),
            transport={
                "provider": "codex",
                "protocol": "websocket",
                "upgrade": {
                    "scheme": "wss",
                    "host": "chatgpt.com",
                    "path": "/backend-api/codex/responses",
                    "request_headers": [],
                    "response_status_code": 101,
                    "response_headers": [],
                },
                "close": None,
                "messages": [],
            },
            events=(disk_tests._make_codex_event(),),
            turn=disk_tests._make_open_turn(),
        )

        async def fail_turn(*_: object) -> None:
            raise OSError("turn write failed")

        with (
            patch.object(storage, "_write_turn_json", side_effect=fail_turn),
            pytest.raises(OSError, match="turn write failed"),
        ):
            await storage.persist_exchange(entry, artifacts)

        assert await storage.read_index(limit=10, offset=0) == []
        with pytest.raises(FileNotFoundError):
            await storage.read_exchange(entry.id)
        assert not any(path.name.endswith((".tmp", ".bak")) for path in storage.root.iterdir())

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
        assert not any(path.name.endswith((".tmp", ".bak")) for path in storage.root.iterdir())

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
        assert not any(path.name.endswith((".tmp", ".bak")) for path in storage.root.iterdir())

    async def test_existing_exchange_restored_on_derived_turn_write_failure(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "persist-old-derived-001"
        original_entry = disk_tests._make_index_entry(exchange_id)
        original_artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"original","max_tokens":1024}',
            request_ir=disk_tests._make_ir(),
            transport={
                "provider": "codex",
                "protocol": "websocket",
                "upgrade": {
                    "scheme": "wss",
                    "host": "chatgpt.com",
                    "path": "/backend-api/codex/responses",
                    "request_headers": [],
                    "response_status_code": 101,
                    "response_headers": [],
                },
                "close": None,
                "messages": [],
            },
        )
        await storage.append_index(original_entry)
        await storage.write_exchange(exchange_id, original_artifacts)
        original_dir = storage._find_exchange_dir(exchange_id)

        updated_artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"updated","max_tokens":2048}',
            request_ir=disk_tests._make_ir(),
            transport=original_artifacts.transport,
            events=(disk_tests._make_codex_event(),),
            turn=disk_tests._make_open_turn(),
        )

        async def fail_turn(*_: object) -> None:
            raise OSError("turn write failed")

        with (
            patch.object(storage, "_write_turn_json", side_effect=fail_turn),
            pytest.raises(OSError, match="turn write failed"),
        ):
            await storage.persist_exchange(original_entry, updated_artifacts)

        restored_dir = storage._find_exchange_dir(exchange_id)
        assert restored_dir == original_dir
        restored_artifacts = await storage.read_exchange(exchange_id)
        assert restored_artifacts.request_raw == original_artifacts.request_raw
        assert restored_artifacts.events is None
        assert restored_artifacts.turn is None
        assert not any(path.name.endswith((".tmp", ".bak")) for path in storage.root.iterdir())

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

    async def test_bootstrap_recovers_missing_index_row_from_entry_sidecar(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "persist-recover-sidecar-001"
        entry = disk_tests._make_index_entry(exchange_id).model_copy(
            update={
                "run_id": "run-sidecar",
                "mutated_manually": True,
                "res": ResStats(stop_reason="completed", text_chars=4),
            }
        )
        artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"restorable","max_tokens":1024}',
            request_ir=disk_tests._make_ir(),
        )

        await storage.persist_exchange(entry, artifacts)
        (storage.root / "index.jsonl").write_text("", encoding="utf-8")

        fresh = DiskStorageBackend(root=str(storage.root))
        recovered = await fresh.read_index_entry(exchange_id)

        assert recovered == IndexEntry.model_validate(entry.model_dump())

    async def test_staged_delete_recovery_binds_by_canonical_path(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "persist-recover-path-001"
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        layout = DiskStorageLayout(storage.root)
        entry = disk_tests._make_index_entry(exchange_id).model_copy(
            update={
                "ts": ts,
                "path": layout.exchange_index_path_for(exchange_id, ts=ts),
            }
        )
        artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"restorable","max_tokens":1024}',
            request_ir=disk_tests._make_ir(),
        )

        await storage.persist_exchange(entry, artifacts)
        live_dir = storage.root / layout.exchange_dir_name(exchange_id, ts=ts)
        assert live_dir.is_dir()
        assert entry.path == layout.exchange_index_path(live_dir.name)

        layout.artifact_paths(live_dir).entry.unlink()
        staged_dir = layout.staged_delete_dir(live_dir)
        live_dir.rename(staged_dir)

        fresh = DiskStorageBackend(root=str(storage.root))
        await fresh.read_index_entry(exchange_id)

        assert live_dir.is_dir()
        assert not staged_dir.exists()

    async def test_bootstrap_recovers_legacy_codex_row_without_entry_sidecar(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "12345678-legacy-codex"
        request_ir = disk_tests._make_ir().model_copy(
            update={
                "provider": "codex",
                "model": "codex/gpt-5-codex",
            }
        )
        turn = disk_tests._make_completed_turn().model_copy(update={"exchange_id": exchange_id})
        artifacts = ExchangeArtifacts(
            request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
            request_ir=request_ir,
            turn=turn,
            events=(
                disk_tests._make_codex_event().model_copy(update={"exchange_id": exchange_id}),
            ),
        )

        await storage.write_exchange(exchange_id, artifacts)

        fresh = DiskStorageBackend(root=str(storage.root))
        recovered = await fresh.read_index_entry(exchange_id)

        assert recovered is not None
        assert recovered.id == exchange_id
        assert recovered.run_id is None
        assert recovered.provider == "codex"
        assert recovered.model == "codex/gpt-5-codex"
        assert recovered.codex_turn is not None
        assert recovered.codex_turn.status == "completed"
        assert recovered.res is not None
        assert recovered.res.stop_reason == "completed"
        assert recovered.res.text_chars == 42
        assert recovered.res.tool_calls == 1
