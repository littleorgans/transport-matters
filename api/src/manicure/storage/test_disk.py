"""Tests for the disk storage backend.

Uses ``tmp_path`` to avoid touching the real filesystem.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any  # Any: opaque rule dicts match StorageBackend API

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from manicure.storage.base import ExchangeArtifacts, IndexEntry, ReqStats
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


class TestWriteAndReadExchange:
    async def test_round_trip(self, storage: DiskStorageBackend) -> None:
        ir = _make_ir()
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        artifacts = ExchangeArtifacts(request_raw=raw, request_ir=ir)

        await storage.write_exchange("abcdef01-1234", artifacts)
        loaded = await storage.read_exchange("abcdef01-1234")

        assert loaded.request_raw == raw
        assert loaded.request_ir == ir
        assert loaded.request_curated_ir is None
        assert loaded.response_raw is None

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

    async def test_not_found(self, storage: DiskStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.read_exchange("nonexistent-id")


class TestRules:
    async def test_load_empty(self, storage: DiskStorageBackend) -> None:
        rules = await storage.load_rules()
        assert rules == []

    async def test_modify_rules_appends(self, storage: DiskStorageBackend) -> None:
        def _seed(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [*data, {"id": "r1", "name": "strip-thinking", "enabled": True}]

        await storage.modify_rules(_seed)
        loaded = await storage.load_rules()
        assert len(loaded) == 1
        assert loaded[0]["name"] == "strip-thinking"

    async def test_modify_rules_replaces(self, storage: DiskStorageBackend) -> None:
        await storage.modify_rules(lambda _: [{"id": "r1", "name": "first"}])
        await storage.modify_rules(lambda _: [{"id": "r2", "name": "second"}])
        loaded = await storage.load_rules()
        assert len(loaded) == 1
        assert loaded[0]["name"] == "second"

    async def test_modify_rules_aborts_on_raise(
        self, storage: DiskStorageBackend
    ) -> None:
        """If fn raises, the write is skipped and state is preserved."""
        await storage.modify_rules(lambda _: [{"id": "r1", "name": "seed"}])

        def _boom(_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
            msg = "intentional"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError):
            await storage.modify_rules(_boom)

        loaded = await storage.load_rules()
        assert len(loaded) == 1
        assert loaded[0]["name"] == "seed"

    async def test_concurrent_modify_no_race(self, storage: DiskStorageBackend) -> None:
        """Concurrent modify_rules appends must not overwrite each other."""

        def make_append(
            n: int,
        ) -> Callable[[list[dict[str, Any]]], list[dict[str, Any]]]:
            def _fn(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
                return [*rules, {"id": f"rule-{n}"}]

            return _fn

        await asyncio.gather(*[storage.modify_rules(make_append(i)) for i in range(8)])

        loaded = await storage.load_rules()
        assert len(loaded) == 8
        ids = {r["id"] for r in loaded}
        assert ids == {f"rule-{i}" for i in range(8)}


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
