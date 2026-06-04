"""HTTP /api/index endpoints: registered, two-phase search, sessions/timeline/diff, raw stream."""

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters.api.v1 import index_routes
from transport_matters.index.db import connect
from transport_matters.index.ingest import RunFacts, bind_exchange, build_wire_job
from transport_matters.index.schema import apply_schema
from transport_matters.ir import Message, TextBlock
from transport_matters.main import create_app
from transport_matters.storage.test_exchange_support import (
    make_artifacts,
    make_index_entry,
    make_request_ir,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import AsyncGenerator, Iterator
    from pathlib import Path


def _populate(db_path: Path) -> None:
    writer = connect(db_path)
    apply_schema(writer)
    entry = make_index_entry(exchange_id="ex1", run_id="run1")
    artifacts = make_artifacts(
        make_request_ir(
            session_id="sess-1",
            messages=[Message(role="user", content=[TextBlock(text="needle token")])],
        )
    )
    run_facts = RunFacts(
        run_id="run1", cwd=None, workspace_slug="", workspace_hash="", started_at="t"
    )
    build_wire_job(entry, artifacts, bind_exchange(entry, artifacts, run_facts)).apply(writer)
    writer.close()


@pytest.fixture
async def index_client(tmp_path: Path) -> AsyncGenerator[AsyncClient]:
    db_path = tmp_path / "index.db"
    _populate(db_path)
    app = create_app()

    def _override() -> Iterator[sqlite3.Connection]:
        reader = connect(db_path, read_only=True)
        try:
            yield reader
        finally:
            reader.close()

    app.dependency_overrides[index_routes._read_connection] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestIndexRoutes:
    async def test_search_round_trip_and_expand(self, index_client: AsyncClient) -> None:
        resp = await index_client.post("/api/index/search", json={"q": "needle"})
        assert resp.status_code == 200
        hits = resp.json()["hits"]
        assert hits
        expanded = await index_client.post(
            "/api/index/search", json={"q": "needle", "expand_ids": [hits[0]["id"]]}
        )
        assert any(b["text"] == "needle token" for b in expanded.json()["bodies"])

    async def test_blocks_phase_two(self, index_client: AsyncClient) -> None:
        hits = (await index_client.post("/api/index/search", json={"q": "needle"})).json()["hits"]
        resp = await index_client.post("/api/index/blocks", json={"ids": [h["id"] for h in hits]})
        assert resp.status_code == 200
        assert resp.json()

    async def test_sessions_and_timeline(self, index_client: AsyncClient) -> None:
        sessions = (await index_client.get("/api/index/sessions")).json()
        assert any(s["session_id"] == "sess-1" for s in sessions)
        timeline = await index_client.get("/api/index/sessions/sess-1/timeline?stream=wire")
        assert timeline.status_code == 200
        assert timeline.json()

    async def test_diff_is_wire_only(self, index_client: AsyncClient) -> None:
        body = (await index_client.get("/api/index/sessions/sess-1/diff")).json()
        assert len(body["wire_only"]) >= 1
        assert body["transcript_only"] == []
        assert body["shared"] == []

    async def test_pivot_empty_without_transcripts(self, index_client: AsyncClient) -> None:
        assert (await index_client.get("/api/index/sessions/sess-1/pivot")).json() == []

    async def test_raw_unknown_exchange_404(self, index_client: AsyncClient) -> None:
        resp = await index_client.get("/api/index/exchanges/missing/raw?part=request")
        assert resp.status_code == 404

    async def test_raw_streams_tier1_bytes(self, index_client: AsyncClient, tmp_path: Path) -> None:
        raw_dir = tmp_path / "exchange-dir"
        raw_dir.mkdir()
        (raw_dir / "request.raw").write_bytes(b"RAWBYTES")
        writer = connect(tmp_path / "index.db")
        writer.execute(
            "INSERT INTO wire_exchange (exchange_id, run_id, provider, model, ts, raw_dir) "
            "VALUES ('raw1', 'run1', 'anthropic', 'm', '2026-06-05T00:00:00Z', ?)",
            (str(raw_dir),),
        )
        writer.close()
        resp = await index_client.get("/api/index/exchanges/raw1/raw?part=request")
        assert resp.status_code == 200
        assert resp.content == b"RAWBYTES"
