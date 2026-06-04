"""Read surface: two-phase search + filters, timeline, pivot/diff (wire-only), raw ref (§13.2)."""

import sqlite3
from pathlib import Path

import pytest

from transport_matters.index.db import connect
from transport_matters.index.ingest import RunFacts, bind_exchange, build_wire_job
from transport_matters.index.models import SearchFilters, SessionFilters
from transport_matters.index.queries import (
    exchange_raw_ref,
    get_block_bodies,
    list_sessions,
    search_blocks,
    session_diff,
    session_pivot,
    session_timeline,
)
from transport_matters.index.schema import apply_schema
from transport_matters.ir import Message, TextBlock
from transport_matters.storage.test_exchange_support import (
    make_artifacts,
    make_index_entry,
    make_request_ir,
)


def _run_facts(run_id: str = "run1") -> RunFacts:
    return RunFacts(
        run_id=run_id,
        cwd=Path("/w"),
        workspace_slug="slug",
        workspace_hash="wh",
        started_at="2026-06-05T00:00:00Z",
    )


def _capture(
    conn: sqlite3.Connection,
    *,
    exchange_id: str = "ex1",
    session_id: str = "sess-1",
    text: str = "needle haystack",
    run_id: str = "run1",
) -> None:
    entry = make_index_entry(exchange_id=exchange_id, run_id=run_id)
    artifacts = make_artifacts(
        make_request_ir(
            session_id=session_id, messages=[Message(role="user", content=[TextBlock(text=text)])]
        )
    )
    binding = bind_exchange(entry, artifacts, _run_facts(run_id))
    build_wire_job(entry, artifacts, binding).apply(conn)


class TestSearch:
    def test_round_trip_metadata_then_bodies(self, conn: sqlite3.Connection) -> None:
        _capture(conn, text="needle haystack")
        hits = search_blocks(conn, "needle", filters=SearchFilters())
        assert hits
        assert "needle" in hits[0].snippet
        assert hits[0].rank is not None
        # Phase 2: bodies fetched separately for chosen ids.
        bodies = get_block_bodies(conn, [h.id for h in hits])
        assert any(b.text == "needle haystack" for b in bodies)

    def test_filters_and_combine(self, conn: sqlite3.Connection) -> None:
        _capture(conn, exchange_id="a", session_id="s1", text="alpha", run_id="r1")
        _capture(conn, exchange_id="b", session_id="s2", text="alpha", run_id="r2")
        run1 = search_blocks(conn, "alpha", filters=SearchFilters(run_id="r1"))
        assert run1 and all(h.run_id == "r1" for h in run1)
        messages = search_blocks(conn, "alpha", filters=SearchFilters(section="messages"))
        assert messages and all(h.section == "messages" for h in messages)
        # The transcript side is empty until slice 4.
        assert search_blocks(conn, "alpha", filters=SearchFilters(stream="transcript")) == []

    def test_block_mode_counts_occurrences(self, conn: sqlite3.Connection) -> None:
        _capture(conn, exchange_id="a", session_id="s1", text="shared")
        _capture(conn, exchange_id="b", session_id="s2", text="shared")
        hits = search_blocks(conn, "shared", filters=SearchFilters(), mode="block")
        block_hit = next(h for h in hits if h.kind == "text")
        assert block_hit.occurrences == 2  # one deduped block, referenced by two exchanges


class TestTimeline:
    def test_wire_timeline_ordered_by_seq(self, conn: sqlite3.Connection) -> None:
        _capture(conn, exchange_id="a", session_id="s1", text="first")
        _capture(conn, exchange_id="b", session_id="s1", text="second")
        entries = session_timeline(conn, "s1", stream="wire")
        assert [e.entity_id for e in entries] == ["a", "b"]
        assert [e.seq for e in entries] == [0, 1]
        assert entries[0].blocks[0].text is None  # no bodies by default
        with_bodies = session_timeline(conn, "s1", stream="wire", with_bodies=True)
        assert with_bodies[0].blocks[0].text == "first"

    def test_seq_range_paginates(self, conn: sqlite3.Connection) -> None:
        for i, eid in enumerate(["a", "b", "c"]):
            _capture(conn, exchange_id=eid, session_id="s1", text=f"t{i}")
        middle = session_timeline(conn, "s1", stream="wire", seq_from=1, seq_to=1)
        assert [e.entity_id for e in middle] == ["b"]

    def test_transcript_timeline_empty_until_slice_4(self, conn: sqlite3.Connection) -> None:
        _capture(conn, session_id="s1", text="x")
        assert session_timeline(conn, "s1", stream="transcript") == []


class TestPivotDiff:
    def test_diff_buckets_all_wire_only(self, conn: sqlite3.Connection) -> None:
        _capture(conn, exchange_id="a", session_id="s1", text="aaa")
        _capture(conn, exchange_id="b", session_id="s1", text="bbb")
        diff = session_diff(conn, "s1")
        assert len(diff.wire_only) == 2
        assert diff.transcript_only == []
        assert diff.shared == []

    def test_pivot_empty_without_transcripts(self, conn: sqlite3.Connection) -> None:
        _capture(conn, session_id="s1", text="x")
        assert session_pivot(conn, "s1") == []


class TestSessionsAndRaw:
    def test_list_sessions_filters(self, conn: sqlite3.Connection) -> None:
        _capture(conn, exchange_id="a", session_id="s1", text="x", run_id="r1")
        rows = list_sessions(conn, filters=SessionFilters(run_id="r1"))
        assert [s.session_id for s in rows] == ["s1"]
        assert list_sessions(conn, filters=SessionFilters(run_id="nope")) == []

    def test_raw_ref_resolves_tier1_paths(self, conn: sqlite3.Connection) -> None:
        _capture(conn, exchange_id="ex1", session_id="s1", text="x")
        ref = exchange_raw_ref(conn, "ex1")
        assert ref.exchange_id == "ex1"
        assert ref.raw_dir
        assert ref.request_raw.endswith("request.raw")
        assert ref.response_raw.endswith("response.raw")
        assert Path(ref.request_raw).parent == Path(ref.raw_dir)

    def test_raw_ref_unknown_raises_keyerror(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(KeyError):
            exchange_raw_ref(conn, "missing")


class TestReadOnlyConnection:
    def test_read_only_rejects_writes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "index.db"
        writer = connect(db_path)
        apply_schema(writer)
        writer.close()
        reader = connect(db_path, read_only=True)
        try:
            with pytest.raises(sqlite3.OperationalError):
                reader.execute("INSERT INTO schema_meta(key, value) VALUES ('x', 'y')")
        finally:
            reader.close()
