"""Tests for the disk storage backend.

Uses ``tmp_path`` to avoid touching the real filesystem.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from manicure.ir import (
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
    UsageStats,
)
from manicure.overrides import OverrideAudit, OverrideAuditEntry
from manicure.storage.base import ExchangeArtifacts, IndexEntry, ReqStats, ResStats
from manicure.storage.disk import DiskStorageBackend


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


def _make_ir() -> InternalRequest:
    return InternalRequest(
        model="anthropic/claude-sonnet-4-20250514",
        provider="anthropic",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


def _make_index_entry(entry_id: str = "ex-001") -> IndexEntry:
    return IndexEntry(
        id=entry_id,
        ts=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        provider="anthropic",
        model="anthropic/claude-sonnet-4-20250514",
        path="/v1/messages",
        req=ReqStats(
            system_parts=0,
            system_chars=0,
            tools_count=0,
            tools_chars=0,
            messages_count=1,
            messages_chars=2,
            total_chars=2,
        ),
    )


def _make_audit() -> OverrideAudit:
    return OverrideAudit(
        entries=[
            OverrideAuditEntry(
                kind="system_part_text",
                target="system:0",
                applied=True,
                chars_delta=-3,
                curated_value="patched",
            )
        ],
        chars_before=10,
        chars_after=7,
    )


class TestAppendAndReadIndex:
    async def test_append_and_read(self, storage: DiskStorageBackend) -> None:
        entry = _make_index_entry()
        await storage.append_index(entry)
        entries = await storage.read_index(limit=10, offset=0)
        assert len(entries) == 1
        assert entries[0].id == "ex-001"

    async def test_read_empty(self, storage: DiskStorageBackend) -> None:
        entries = await storage.read_index(limit=10, offset=0)
        assert entries == []

    async def test_pagination(self, storage: DiskStorageBackend) -> None:
        for i in range(5):
            await storage.append_index(_make_index_entry(f"ex-{i:03d}"))
        page = await storage.read_index(limit=2, offset=1)
        assert len(page) == 2
        assert page[0].id == "ex-001"
        assert page[1].id == "ex-002"

    async def test_upsert_replaces_existing_row(
        self, storage: DiskStorageBackend
    ) -> None:
        original = _make_index_entry("ex-upsert")
        await storage.append_index(original)

        updated = original.model_copy(
            update={"res": ResStats(stop_reason="completed", text_chars=12)}
        )
        await storage.upsert_index(updated)

        entries = await storage.read_index(limit=10, offset=0)
        assert len(entries) == 1
        assert entries[0].id == "ex-upsert"
        assert entries[0].res is not None
        assert entries[0].res.stop_reason == "completed"


class TestWriteAndReadExchange:
    async def test_round_trip(self, storage: DiskStorageBackend) -> None:
        ir = _make_ir()
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        artifacts = ExchangeArtifacts(request_raw=raw, request_ir=ir)

        await storage.write_exchange("abcdef01-1234", artifacts)
        loaded = await storage.read_exchange("abcdef01-1234")

        assert loaded.request_raw == raw
        assert loaded.request_ir == ir
        assert loaded.request_curated_raw is None
        assert loaded.request_curated_ir is None
        assert loaded.request_audit is None
        assert loaded.response_raw is None
        assert loaded.transport is None

    async def test_with_response(self, storage: DiskStorageBackend) -> None:
        from manicure.ir import InternalResponse, UsageStats

        ir = _make_ir()
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        resp_raw = b'{"id":"msg_01","model":"claude-sonnet-4-20250514","content":[]}'
        resp_ir = InternalResponse(
            id="msg_01",
            model="anthropic/claude-sonnet-4-20250514",
            provider="anthropic",
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=10, output_tokens=20),
            content=[],
        )

        artifacts = ExchangeArtifacts(
            request_raw=raw,
            request_ir=ir,
            response_raw=resp_raw,
            response_ir=resp_ir,
        )
        await storage.write_exchange("bbccdd02-5678", artifacts)
        loaded = await storage.read_exchange("bbccdd02-5678")

        assert loaded.response_raw == resp_raw
        assert loaded.response_ir is not None
        assert loaded.response_ir.id == "msg_01"

    async def test_with_curated_request_audit_and_transport(
        self, storage: DiskStorageBackend
    ) -> None:
        ir = _make_ir()
        curated_raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":256}'
        artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
            request_ir=ir,
            request_curated_raw=curated_raw,
            request_curated_ir=ir.model_copy(
                update={
                    "messages": [
                        Message(role="user", content=[TextBlock(text="patched")]),
                    ]
                }
            ),
            request_audit=_make_audit(),
            transport={
                "provider": "codex",
                "protocol": "websocket",
                "upgrade": {
                    "scheme": "wss",
                    "host": "chatgpt.com",
                    "path": "/backend-api/codex/responses",
                    "request_headers": [
                        {"name": "authorization", "value": "Bearer super-secret"},
                        {"name": "x-test", "value": "1"},
                    ],
                    "response_status_code": 101,
                    "response_headers": [
                        {"name": "set-cookie", "value": "session=secret; Path=/"},
                        {"name": "x-upstream", "value": "chatgpt"},
                    ],
                },
                "close": {
                    "close_code": 1000,
                    "close_reason": "done",
                    "closed_by_client": False,
                    "initial_client_frame_captured": True,
                    "client_message_count": 1,
                    "server_message_count": 2,
                },
                "messages": [
                    {
                        "direction": "client",
                        "is_text": True,
                        "size_bytes": 24,
                        "dropped": False,
                        "event_type": "response.create",
                        "payload_text": '{"type":"response.create"}',
                        "payload_json": {"type": "response.create"},
                        "payload_base64": None,
                    }
                ],
            },
        )

        await storage.write_exchange("codex0001-5678", artifacts)
        loaded = await storage.read_exchange("codex0001-5678")

        assert loaded.request_curated_raw == curated_raw
        assert loaded.request_curated_ir is not None
        block = loaded.request_curated_ir.messages[0].content[0]
        assert isinstance(block, TextBlock)
        assert block.text == "patched"
        assert loaded.request_audit is not None
        assert loaded.request_audit.entries[0].target == "system:0"
        assert loaded.transport is not None
        assert loaded.transport.provider == "codex"
        assert loaded.transport.close is not None
        assert loaded.transport.close.close_code == 1000
        request_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.request_headers
        }
        response_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.response_headers
        }
        assert request_headers["authorization"] == "Bearer [redacted]"
        assert request_headers["x-test"] == "1"
        assert response_headers["set-cookie"] == "[redacted]"
        assert response_headers["x-upstream"] == "chatgpt"
        assert loaded.transport.messages[0].event_type == "response.create"

    async def test_rewrite_existing_exchange_dir(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "rewrite01-1234"
        original_ir = _make_ir()
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(
                request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
                request_ir=original_ir,
            ),
        )
        original_dir = storage._find_exchange_dir(exchange_id)

        final_response = InternalResponse(
            id="msg_final",
            model="anthropic/claude-sonnet-4-20250514",
            provider="anthropic",
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=10, output_tokens=20),
            content=[TextBlock(text="done")],
        )
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(
                request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
                request_ir=original_ir,
                request_curated_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":256}',
                request_curated_ir=original_ir.model_copy(
                    update={
                        "messages": [
                            Message(role="user", content=[TextBlock(text="patched")])
                        ]
                    }
                ),
                response_raw=b'{"id":"msg_final"}',
                response_ir=final_response,
            ),
        )

        dirs = [path for path in storage.root.iterdir() if path.is_dir()]
        assert dirs == [original_dir]
        loaded = await storage.read_exchange(exchange_id)
        assert loaded.request_curated_raw is not None
        assert loaded.response_ir is not None
        assert loaded.response_ir.id == "msg_final"

    async def test_read_exchange_redacts_and_rewrites_legacy_transport_headers(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "legacy000-5678"
        exchange_dir = storage.root / f"20250601T120000Z-{exchange_id[:8]}"
        exchange_dir.mkdir()
        (exchange_dir / "request.raw").write_bytes(
            b'{"type":"response.create","model":"gpt-5-codex"}'
        )
        (exchange_dir / "request.ir.json").write_text(_make_ir().model_dump_json())
        (exchange_dir / "transport.json").write_text(
            """
{
  "provider": "codex",
  "protocol": "websocket",
  "upgrade": {
    "scheme": "wss",
    "host": "chatgpt.com",
    "path": "/backend-api/codex/responses",
    "request_headers": [
      {"name": "authorization", "value": "Bearer legacy-secret"},
      {"name": "origin", "value": "https://chatgpt.com"}
    ],
    "response_status_code": 403,
    "response_headers": [
      {"name": "set-cookie", "value": "session=legacy; Path=/"},
      {"name": "content-type", "value": "application/json"}
    ]
  },
  "close": null,
  "messages": []
}
""".strip()
        )

        loaded = await storage.read_exchange(exchange_id)

        assert loaded.transport is not None
        request_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.request_headers
        }
        response_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.response_headers
        }
        assert request_headers["authorization"] == "Bearer [redacted]"
        assert request_headers["origin"] == "https://chatgpt.com"
        assert response_headers["set-cookie"] == "[redacted]"
        assert response_headers["content-type"] == "application/json"

        persisted = (exchange_dir / "transport.json").read_text()
        assert "legacy-secret" not in persisted
        assert "session=legacy" not in persisted
        assert "Bearer [redacted]" in persisted

    async def test_not_found(self, storage: DiskStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.read_exchange("nonexistent-id")


class TestReadIndexEntry:
    async def test_returns_none_when_empty(self, storage: DiskStorageBackend) -> None:
        result = await storage.read_index_entry("nonexistent")
        assert result is None

    async def test_returns_correct_entry(self, storage: DiskStorageBackend) -> None:
        entry_a = _make_index_entry("aaaa1111")
        entry_b = _make_index_entry("bbbb2222")
        await storage.append_index(entry_a)
        await storage.append_index(entry_b)

        found = await storage.read_index_entry("aaaa1111")
        assert found is not None
        assert found.id == "aaaa1111"

        found_b = await storage.read_index_entry("bbbb2222")
        assert found_b is not None
        assert found_b.id == "bbbb2222"

    async def test_consistent_with_read_index(
        self, storage: DiskStorageBackend
    ) -> None:
        ids = [f"id{i:04d}" for i in range(5)]
        for eid in ids:
            await storage.append_index(_make_index_entry(eid))

        all_entries = await storage.read_index(limit=100, offset=0)
        assert len(all_entries) == 5

        for eid in ids:
            found = await storage.read_index_entry(eid)
            assert found is not None
            assert found.id == eid

    async def test_cache_updated_after_append(
        self, storage: DiskStorageBackend
    ) -> None:
        """Cache should reflect entries added after first read."""
        assert await storage.read_index_entry("cached-id") is None
        await storage.append_index(_make_index_entry("cached-id"))
        found = await storage.read_index_entry("cached-id")
        assert found is not None
        assert found.id == "cached-id"


class TestDeleteExchange:
    async def test_removes_index_row_and_artifacts(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "deadbeef-1234"
        await storage.append_index(_make_index_entry(exchange_id))
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(request_raw=b"{}", request_ir=_make_ir()),
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
        entry = _make_index_entry(exchange_id)
        artifacts = ExchangeArtifacts(request_raw=b"{}", request_ir=_make_ir())
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

    async def test_rewrite_failure_preserves_cache_order(
        self, storage: DiskStorageBackend
    ) -> None:
        first = _make_index_entry("deadbeef-first")
        middle = _make_index_entry("deadbeef-middle")
        last = _make_index_entry("deadbeef-last")
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


class TestCacheCreationBackfill:
    """Lazy backfill of cache_creation_input_tokens on first index read.

    Rows written before ResStats carried the field stored zero. The full
    UsageStats survives in response.ir.json, so _ensure_index_cache can
    rehydrate the missing value on first load and rewrite the index in
    place. Rows whose artifact also reports zero are untouched.
    """

    async def _seed_exchange(
        self,
        storage: DiskStorageBackend,
        exchange_id: str,
        usage: UsageStats,
    ) -> None:
        """Write a request + response artifact pair into the exchange dir."""
        ir = _make_ir()
        resp_ir = InternalResponse(
            id=f"msg_{exchange_id}",
            model="anthropic/claude-sonnet-4-20250514",
            provider="anthropic",
            stop_reason="end_turn",
            usage=usage,
            content=[],
        )
        artifacts = ExchangeArtifacts(
            request_raw=b"{}",
            request_ir=ir,
            response_raw=b"{}",
            response_ir=resp_ir,
        )
        await storage.write_exchange(exchange_id, artifacts)

    async def test_backfills_zero_row_from_artifact(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "aaaa0000-1111-2222-3333-444455556666"
        # Old-style index entry: res present, cache_creation is zero.
        entry = _make_index_entry(exchange_id).model_copy(
            update={
                "res": ResStats(
                    input_tokens=100,
                    output_tokens=50,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=5,
                )
            }
        )
        await storage.append_index(entry)
        # Artifact carries the truth (200 tokens written to cache this turn).
        await self._seed_exchange(
            storage,
            exchange_id,
            UsageStats(
                input_tokens=100,
                output_tokens=50,
                cache_creation_input_tokens=200,
                cache_read_input_tokens=5,
            ),
        )

        # Drop the in-memory cache so the next read triggers the backfill.
        storage._index_cache = None

        reloaded = await storage.read_index_entry(exchange_id)
        assert reloaded is not None
        assert reloaded.res is not None
        assert reloaded.res.cache_creation_input_tokens == 200
        # Other fields stay intact.
        assert reloaded.res.input_tokens == 100
        assert reloaded.res.cache_read_input_tokens == 5

    async def test_disk_rewrite_is_durable(
        self, storage: DiskStorageBackend, tmp_path: Path
    ) -> None:
        """A second DiskStorageBackend reading the same root sees the
        backfilled value without having to redo the work."""
        exchange_id = "bbbb0000-1111-2222-3333-444455556666"
        entry = _make_index_entry(exchange_id).model_copy(
            update={"res": ResStats(input_tokens=10, cache_creation_input_tokens=0)}
        )
        await storage.append_index(entry)
        await self._seed_exchange(
            storage,
            exchange_id,
            UsageStats(input_tokens=10, cache_creation_input_tokens=77),
        )
        storage._index_cache = None
        _ = await storage.read_index_entry(exchange_id)  # triggers backfill + rewrite

        fresh = DiskStorageBackend(root=str(tmp_path))
        reloaded = await fresh.read_index_entry(exchange_id)
        assert reloaded is not None
        assert reloaded.res is not None
        assert reloaded.res.cache_creation_input_tokens == 77

    async def test_leaves_legitimate_zero_rows_alone(
        self, storage: DiskStorageBackend
    ) -> None:
        """If the artifact also reports zero, the row is not rewritten."""
        exchange_id = "cccc0000-1111-2222-3333-444455556666"
        entry = _make_index_entry(exchange_id).model_copy(
            update={"res": ResStats(input_tokens=5, cache_creation_input_tokens=0)}
        )
        await storage.append_index(entry)
        await self._seed_exchange(
            storage,
            exchange_id,
            UsageStats(input_tokens=5, cache_creation_input_tokens=0),
        )
        storage._index_cache = None

        reloaded = await storage.read_index_entry(exchange_id)
        assert reloaded is not None
        assert reloaded.res is not None
        assert reloaded.res.cache_creation_input_tokens == 0

    async def test_rows_without_artifact_are_skipped(
        self, storage: DiskStorageBackend
    ) -> None:
        """Rows whose exchange dir is missing (e.g. pruned) stay as-is."""
        exchange_id = "dddd0000-1111-2222-3333-444455556666"
        entry = _make_index_entry(exchange_id).model_copy(
            update={"res": ResStats(input_tokens=5, cache_creation_input_tokens=0)}
        )
        await storage.append_index(entry)
        storage._index_cache = None

        reloaded = await storage.read_index_entry(exchange_id)
        assert reloaded is not None
        assert reloaded.res is not None
        assert reloaded.res.cache_creation_input_tokens == 0


class TestAtomicWrite:
    async def test_no_tmp_dir_after_successful_write(
        self, storage: DiskStorageBackend
    ) -> None:
        """Successful write should leave no .tmp directories."""
        ir = _make_ir()
        raw = b'{"model":"test","max_tokens":1024}'
        artifacts = ExchangeArtifacts(request_raw=raw, request_ir=ir)

        await storage.write_exchange("atomic-001", artifacts)

        tmp_dirs = [d for d in storage.root.iterdir() if d.name.endswith(".tmp")]
        assert tmp_dirs == []

    async def test_crash_recovery_cleans_tmp_on_init(self, tmp_path: Path) -> None:
        """Leftover .tmp dirs from interrupted writes are cleaned up on init."""
        leftover = tmp_path / "20260101T000000Z-deadbeef.tmp"
        leftover.mkdir()
        (leftover / "request.raw").write_bytes(b"partial")

        DiskStorageBackend(root=str(tmp_path))

        assert not leftover.exists()
        # Normal dirs are not cleaned
        normal = tmp_path / "20260101T000000Z-abcd1234"
        normal.mkdir()
        DiskStorageBackend(root=str(tmp_path))
        assert normal.exists()

    async def test_failed_write_cleans_up_tmp(
        self, storage: DiskStorageBackend
    ) -> None:
        """If write_exchange fails mid-write, the .tmp dir is removed."""
        ir = _make_ir()
        raw = b'{"model":"test","max_tokens":1024}'
        artifacts = ExchangeArtifacts(request_raw=raw, request_ir=ir)

        with (
            patch("aiofiles.open", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            await storage.write_exchange("fail-001", artifacts)

        tmp_dirs = [d for d in storage.root.iterdir() if d.name.endswith(".tmp")]
        assert tmp_dirs == []

    async def test_rewrite_failure_restores_original_exchange_dir(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "rewrite-fail-001"
        original_ir = _make_ir()
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(
                request_raw=b'{"model":"original","max_tokens":1024}',
                request_ir=original_ir,
            ),
        )

        original_dir = storage._find_exchange_dir(exchange_id)
        original_raw = (original_dir / "request.raw").read_bytes()
        original_rename = Path.rename

        def fail_final_rename(self: Path, target: Path) -> Path:
            if self.name.endswith(".tmp") and target == original_dir:
                raise OSError("rename failed")
            return original_rename(self, target)

        with (
            patch.object(Path, "rename", autospec=True, side_effect=fail_final_rename),
            pytest.raises(OSError, match="rename failed"),
        ):
            await storage.write_exchange(
                exchange_id,
                ExchangeArtifacts(
                    request_raw=b'{"model":"rewritten","max_tokens":2048}',
                    request_ir=original_ir,
                ),
            )

        restored_dir = storage._find_exchange_dir(exchange_id)
        assert restored_dir == original_dir
        assert (restored_dir / "request.raw").read_bytes() == original_raw
        assert not any(path.name.endswith(".tmp") for path in storage.root.iterdir())
