"""Wire ingest: binding resolution, field mapping, ordered edges, idempotency (§13.2 + §7.1)."""

from pathlib import Path
from typing import TYPE_CHECKING

from transport_matters.index.db import connect
from transport_matters.index.ingest import RunFacts, bind_exchange, build_wire_job, make_index_sink
from transport_matters.index.writer import IndexWriter
from transport_matters.ir import Message, SystemPart, TextBlock
from transport_matters.storage.base import ReqStats, ResStats
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.test_exchange_support import (
    make_artifacts,
    make_index_entry,
    make_request_ir,
    make_response_ir,
)
from transport_matters.test_override_support import TOOL_BASH

if TYPE_CHECKING:
    import sqlite3


def _run_facts(run_id: str | None = "run1") -> RunFacts:
    return RunFacts(
        run_id=run_id,
        cwd=Path("/w"),
        workspace_slug="slug",
        workspace_hash="hash",
        started_at="2026-06-05T00:00:00Z",
    )


class TestBindExchange:
    def test_minted_provider_uses_correlation_id_directly(self) -> None:
        entry = make_index_entry(provider="anthropic")
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        assert binding is not None
        assert binding.minted_session_id == "sess-1"
        assert binding.native_session_id is None

    def test_readback_provider_synthesizes(self) -> None:
        entry = make_index_entry(provider="codex")
        artifacts = make_artifacts(make_request_ir(session_id="native-9"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        assert binding is not None
        assert binding.native_session_id == "native-9"
        assert binding.minted_session_id is None

    def test_no_correlation_id_returns_none(self) -> None:
        artifacts = make_artifacts(make_request_ir(session_id=None))
        assert bind_exchange(make_index_entry(), artifacts, _run_facts()) is None

    def test_no_run_id_returns_none(self) -> None:
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        assert bind_exchange(make_index_entry(), artifacts, _run_facts(run_id=None)) is None


class TestBuildWireJob:
    def test_row_reuses_req_stats_and_points_raw_dir(self, conn: sqlite3.Connection) -> None:
        req = ReqStats(system_chars=10, tools_chars=20, messages_chars=30)
        res = ResStats(stop_reason="end_turn", input_tokens=5, output_tokens=7)
        entry = make_index_entry(req=req, res=res, mutated_manually=True)
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        build_wire_job(entry, artifacts, binding).apply(conn)

        row = conn.execute(
            "SELECT session_id, run_id, provider, model, req_system_chars, req_tools_chars, "
            "req_messages_chars, req_tokens, res_tokens, stop_reason, mutated_manually, raw_dir, "
            "seq FROM wire_exchange WHERE exchange_id = 'ex1'"
        ).fetchone()
        assert row[0:4] == ("sess-1", "run1", "anthropic", "claude-3")
        assert row[4:7] == (10, 20, 30)  # ReqStats reused, not recomputed
        assert (row[7], row[8], row[9]) == (5, 7, "end_turn")
        assert row[10] == 1  # mutated_manually
        assert Path(row[11]).name == DiskStorageLayout().exchange_dir_name(entry.id, ts=entry.ts)
        assert row[12] == 0  # seq = MAX(seq)+1 within a fresh session
        assert (
            conn.execute("SELECT COUNT(*) FROM session WHERE session_id = 'sess-1'").fetchone()[0]
            == 1
        )

    def test_null_session_when_uncorrelated(self, conn: sqlite3.Connection) -> None:
        entry = make_index_entry()
        artifacts = make_artifacts(make_request_ir(session_id=None))
        build_wire_job(entry, artifacts, None).apply(conn)
        session_id, seq = conn.execute(
            "SELECT session_id, seq FROM wire_exchange WHERE exchange_id = 'ex1'"
        ).fetchone()
        assert session_id is None
        assert seq is None  # seq is per-session; NULL while uncorrelated
        assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 0

    def test_edges_ordered_system_tools_messages_response(self, conn: sqlite3.Connection) -> None:
        request = make_request_ir(
            session_id="sess-1",
            system=[SystemPart(text="S")],
            tools=[TOOL_BASH],
            messages=[Message(role="user", content=[TextBlock(text="U")])],
        )
        entry = make_index_entry()
        artifacts = make_artifacts(request, make_response_ir())
        binding = bind_exchange(entry, artifacts, _run_facts())
        build_wire_job(entry, artifacts, binding).apply(conn)
        edges = conn.execute(
            "SELECT pos, role, section FROM exchange_block WHERE exchange_id = 'ex1' ORDER BY pos"
        ).fetchall()
        assert edges == [
            (0, "system", "system"),
            (1, "system", "tools"),
            (2, "user", "messages"),
            (3, "assistant", "response"),
        ]

    def test_idempotent_reingest_replaces_edges_and_keeps_one_row(
        self, conn: sqlite3.Connection
    ) -> None:
        request = make_request_ir(
            session_id="sess-1", messages=[Message(role="user", content=[TextBlock(text="U")])]
        )
        entry = make_index_entry()
        artifacts = make_artifacts(request)
        binding = bind_exchange(entry, artifacts, _run_facts())
        build_wire_job(entry, artifacts, binding).apply(conn)
        build_wire_job(entry, artifacts, binding).apply(conn)
        assert conn.execute("SELECT COUNT(*) FROM wire_exchange").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM exchange_block WHERE exchange_id = 'ex1'"
            ).fetchone()[0]
            == 1
        )

    def test_seq_backfilled_when_correlation_arrives_later(self, conn: sqlite3.Connection) -> None:
        entry = make_index_entry()
        # First write is uncorrelated: session_id and seq are both NULL.
        build_wire_job(entry, make_artifacts(make_request_ir(session_id=None)), None).apply(conn)
        assert conn.execute(
            "SELECT session_id, seq FROM wire_exchange WHERE exchange_id = 'ex1'"
        ).fetchone() == (None, None)
        # A later correlation upsert backfills session_id AND assigns seq (not left NULL).
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        build_wire_job(entry, artifacts, binding).apply(conn)
        assert conn.execute(
            "SELECT session_id, seq FROM wire_exchange WHERE exchange_id = 'ex1'"
        ).fetchone() == ("sess-1", 0)

    def test_seq_increments_per_session_and_is_preserved_on_reingest(
        self, conn: sqlite3.Connection
    ) -> None:
        run_facts = _run_facts()
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        first = make_index_entry(exchange_id="a")
        second = make_index_entry(exchange_id="b")
        build_wire_job(first, artifacts, bind_exchange(first, artifacts, run_facts)).apply(conn)
        build_wire_job(second, artifacts, bind_exchange(second, artifacts, run_facts)).apply(conn)
        assert dict(conn.execute("SELECT exchange_id, seq FROM wire_exchange").fetchall()) == {
            "a": 0,
            "b": 1,
        }
        # Re-ingesting an already-correlated exchange must not renumber it.
        build_wire_job(first, artifacts, bind_exchange(first, artifacts, run_facts)).apply(conn)
        assert (
            conn.execute("SELECT seq FROM wire_exchange WHERE exchange_id = 'a'").fetchone()[0] == 0
        )


class TestMakeIndexSink:
    def test_end_to_end_capture_creates_wire_and_session_rows(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "index.db")
        writer = IndexWriter(db_path, flush_ms=5)
        writer.start()
        sink = make_index_sink(writer, _run_facts())
        entry = make_index_entry(req=ReqStats(messages_chars=5))
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        sink(entry, artifacts)
        sink(entry, artifacts)  # idempotent re-capture
        writer.stop(drain=True)

        verify = connect(db_path)
        try:
            assert verify.execute("SELECT COUNT(*) FROM wire_exchange").fetchone()[0] == 1
            assert verify.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1
            assert (
                verify.execute(
                    "SELECT session_id FROM wire_exchange WHERE exchange_id = 'ex1'"
                ).fetchone()[0]
                == "sess-1"
            )
        finally:
            verify.close()
