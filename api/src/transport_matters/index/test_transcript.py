"""Transcript write path (§7.3) and the first real wire↔transcript DIFF (§8.4) ★ MILESTONE.

The DIFF is the whole point (§1.1): the wire and the claude transcript bind to the SAME
session_id, and because parts are ``ir.ContentBlock``s, identical content dedups to one block.
``session_diff`` then buckets shared / wire_only / transcript_only exactly.
"""

from typing import TYPE_CHECKING

from transport_matters.index.adapters.base import NormalizedTurn, SessionBinding
from transport_matters.index.ingest import (
    RunFacts,
    bind_exchange,
    build_transcript_job,
    build_wire_job,
)
from transport_matters.index.models import Correspondence
from transport_matters.index.queries import session_diff, session_pivot
from transport_matters.ir import Message, SystemPart, TextBlock
from transport_matters.storage.test_exchange_support import (
    make_artifacts,
    make_index_entry,
    make_request_ir,
    make_response_ir,
)

if TYPE_CHECKING:
    import sqlite3

    from transport_matters.ir import ContentBlock


def _binding() -> SessionBinding:
    return SessionBinding(
        session_id="sess-1",
        provider="anthropic",
        run_id="run1",
        cwd="/w",
        workspace_slug="slug",
        workspace_hash="hash",
        started_at="t",
        cli="claude",
        native_session_id="sess-1",
        minted=False,
    )


def _turn(*parts: ContentBlock, turn_id: str = "turn-1") -> NormalizedTurn:
    return NormalizedTurn(
        turn_id=turn_id,
        session_id="sess-1",
        run_id="run1",
        provider="anthropic",
        cli="claude",
        role="assistant",
        seq=0,
        is_sidechain=False,
        parts=list(parts),
    )


def _run_facts() -> RunFacts:
    from pathlib import Path

    return RunFacts(
        run_id="run1",
        cwd=Path("/w"),
        workspace_slug="slug",
        workspace_hash="hash",
        started_at="t",
    )


def _block_id(conn: sqlite3.Connection, text: str) -> int:
    return int(conn.execute("SELECT id FROM block WHERE text = ?", (text,)).fetchone()[0])


class TestBuildTranscriptJob:
    def test_writes_turn_and_edges_with_the_turn_role(self, conn: sqlite3.Connection) -> None:
        build_transcript_job(_turn(TextBlock(text="a"), TextBlock(text="b")), _binding()).apply(
            conn
        )
        session_id, role, seq = conn.execute(
            "SELECT session_id, role, seq FROM transcript_turn WHERE turn_id = 'turn-1'"
        ).fetchone()
        assert (session_id, role, seq) == ("sess-1", "assistant", 0)
        edges = conn.execute(
            "SELECT pos, role FROM turn_block WHERE turn_id = 'turn-1' ORDER BY pos"
        ).fetchall()
        assert edges == [(0, "assistant"), (1, "assistant")]  # the turn's role on every edge (§4.3)
        assert (
            conn.execute("SELECT COUNT(*) FROM session WHERE session_id = 'sess-1'").fetchone()[0]
            == 1
        )

    def test_idempotent_reingest(self, conn: sqlite3.Connection) -> None:
        build_transcript_job(_turn(TextBlock(text="a")), _binding()).apply(conn)
        build_transcript_job(_turn(TextBlock(text="a")), _binding()).apply(conn)
        assert conn.execute("SELECT COUNT(*) FROM transcript_turn").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM turn_block WHERE turn_id = 'turn-1'").fetchone()[0]
            == 1
        )


class TestCorrelationDiff:
    def test_wire_transcript_pivot_and_diff(self, conn: sqlite3.Connection) -> None:
        # WIRE under sess-1: system "sys", message "shared content", response "answer".
        entry = make_index_entry(exchange_id="ex1", run_id="run1")
        request = make_request_ir(
            session_id="sess-1",
            system=[SystemPart(text="sys")],
            messages=[Message(role="user", content=[TextBlock(text="shared content")])],
        )
        artifacts = make_artifacts(request, make_response_ir())  # response = TextBlock("answer")
        build_wire_job(entry, artifacts, bind_exchange(entry, artifacts, _run_facts())).apply(conn)
        # TRANSCRIPT under sess-1: "shared content" (shared) + "transcript only".
        turn = _turn(TextBlock(text="shared content"), TextBlock(text="transcript only"))
        build_transcript_job(turn, _binding()).apply(conn)

        diff = session_diff(conn, "sess-1")
        assert diff.shared == [_block_id(conn, "shared content")]
        assert _block_id(conn, "transcript only") in diff.transcript_only
        assert _block_id(conn, "answer") in diff.wire_only  # the response is wire-only
        assert _block_id(conn, "transcript only") not in diff.wire_only

        pivot = session_pivot(conn, "sess-1")
        assert pivot == [Correspondence(exchange_id="ex1", turn_id="turn-1", shared_blocks=1)]
