"""Tests for the exchanges API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from manicure.main import create_app
from manicure.storage import init_storage, reset_storage
from manicure.storage.base import ExchangeArtifacts, IndexEntry, ReqStats

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _setup_storage(tmp_path: Path) -> Generator[None]:
    """Initialise storage with a temp dir before each test."""
    reset_storage()
    init_storage(root=tmp_path)
    yield
    reset_storage()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _make_index_entry(entry_id: str = "ex-001") -> IndexEntry:
    return IndexEntry(
        id=entry_id,
        ts=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        provider="anthropic",
        model="anthropic/claude-sonnet-4-20250514",
        path="exchanges/20250601T120000-ex-001/",
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


class TestListExchanges:
    async def test_list_empty(self, client: AsyncClient) -> None:
        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_after_write(self, client: AsyncClient) -> None:
        from manicure.storage import get_storage

        storage = get_storage()
        entry = _make_index_entry()
        await storage.append_index(entry)

        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "ex-001"


class TestGetExchange:
    async def test_get_not_found(self, client: AsyncClient) -> None:
        response = await client.get("/api/exchanges/nonexistent")
        assert response.status_code == 404

    async def test_get_existing(self, client: AsyncClient) -> None:
        from manicure.storage import get_storage

        storage = get_storage()
        entry = _make_index_entry()
        ir = _make_ir()
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        artifacts = ExchangeArtifacts(request_raw=raw, request_ir=ir)

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["request_ir"]["model"] == "anthropic/claude-sonnet-4-20250514"
        assert data["request_curated_ir"] is None
        assert data["response_ir"] is None

    async def test_get_existing_surfaces_curated_ir(self, client: AsyncClient) -> None:
        """When a curated IR was persisted (pipeline or breakpoint edit), the
        route must surface it so the UI can show what was actually sent.

        Regression: the route previously dropped request_curated_ir on the
        floor, so edits made at a breakpoint were invisible in the UI even
        though they were correctly written to disk.
        """
        from manicure.storage import get_storage

        storage = get_storage()
        entry = _make_index_entry()
        ir = _make_ir()
        # Simulate a user edit: curated carries a different message body.
        curated_ir = ir.model_copy(
            update={
                "messages": [
                    Message(role="user", content=[TextBlock(text="edited")]),
                ],
            }
        )
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        artifacts = ExchangeArtifacts(
            request_raw=raw,
            request_ir=ir,
            request_curated_ir=curated_ir,
        )

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["request_ir"]["messages"][0]["content"][0]["text"] == "hi"
        assert data["request_curated_ir"] is not None
        assert (
            data["request_curated_ir"]["messages"][0]["content"][0]["text"] == "edited"
        )
