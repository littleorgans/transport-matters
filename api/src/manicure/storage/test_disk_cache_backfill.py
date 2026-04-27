"""Tests for disk index cache recovery behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

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
from manicure.storage.base import (
    ExchangeArtifacts,
    IndexEntry,
    ReqStats,
    ResStats,
    SpawnAnchor,
)
from manicure.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def storage(tmp_path: Path) -> DiskStorageBackend:
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


class TestCacheCreationBackfill:
    """Lazy backfill of cache_creation_input_tokens on first index read."""

    async def _seed_exchange(
        self,
        storage: DiskStorageBackend,
        exchange_id: str,
        usage: UsageStats,
    ) -> None:
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
            request_ir=_make_ir(),
            response_raw=b"{}",
            response_ir=resp_ir,
        )
        await storage.write_exchange(exchange_id, artifacts)

    async def test_backfills_zero_row_from_artifact(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "aaaa0000-1111-2222-3333-444455556666"
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

        storage._index_cache = None

        reloaded = await storage.read_index_entry(exchange_id)
        assert reloaded is not None
        assert reloaded.res is not None
        assert reloaded.res.cache_creation_input_tokens == 200
        assert reloaded.res.input_tokens == 100
        assert reloaded.res.cache_read_input_tokens == 5

    async def test_disk_rewrite_is_durable(
        self, storage: DiskStorageBackend, tmp_path: Path
    ) -> None:
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
        _ = await storage.read_index_entry(exchange_id)

        fresh = DiskStorageBackend(root=str(tmp_path))
        reloaded = await fresh.read_index_entry(exchange_id)
        assert reloaded is not None
        assert reloaded.res is not None
        assert reloaded.res.cache_creation_input_tokens == 77

    async def test_leaves_legitimate_zero_rows_alone(
        self, storage: DiskStorageBackend
    ) -> None:
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


class TestSpawnAnchorRoundTrip:
    """Cache reload preserves the nested SpawnAnchor field on IndexEntry,
    including the explicit null shape that distinguishes a missing anchor
    from absent track metadata."""

    async def test_preserves_populated_spawn_anchor(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "eeee0000-1111-2222-3333-444455556666"
        original_anchor = SpawnAnchor(
            track_spawn_exchange_id="parent-exchange",
            track_spawn_tool_use_id="toolu_worker",
            track_spawn_order=1,
        )
        entry = _make_index_entry(exchange_id).model_copy(
            update={
                "track_id": "toolu_worker",
                "parent_track_id": "root-track",
                "track_display_name": "worker",
                "track_role": "subagent",
                "spawn_anchor": original_anchor,
            }
        )
        await storage.append_index(entry)

        storage._index_cache = None

        reloaded = await storage.read_index_entry(exchange_id)
        assert reloaded is not None
        assert reloaded.spawn_anchor == original_anchor

    async def test_preserves_null_spawn_anchor(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "ffff0000-1111-2222-3333-444455556666"
        entry = _make_index_entry(exchange_id).model_copy(update={"spawn_anchor": None})
        await storage.append_index(entry)

        storage._index_cache = None

        reloaded = await storage.read_index_entry(exchange_id)
        assert reloaded is not None
        assert reloaded.spawn_anchor is None
