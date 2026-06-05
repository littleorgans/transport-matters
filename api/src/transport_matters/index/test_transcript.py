"""Transcript write path (§7.3) and the first real wire↔transcript DIFF (§8.4) ★ MILESTONE.

The DIFF is the whole point (§1.1): the wire and the claude transcript bind to the SAME
session_id, and because parts are ``ir.ContentBlock``s, identical content dedups to one block.
``session_diff`` then buckets shared / wire_only / transcript_only exactly.
"""

from typing import TYPE_CHECKING

from transport_matters.index.adapters.base import (
    NormalizedTurn,
    RunContext,
    SessionBinding,
    TurnContext,
)
from transport_matters.index.adapters.codex import CodexAdapter
from transport_matters.index.conftest import make_binding
from transport_matters.index.ingest import (
    RunFacts,
    bind_exchange,
    build_transcript_job,
    build_wire_job,
)
from transport_matters.index.models import Correspondence
from transport_matters.index.queries import session_diff, session_pivot
from transport_matters.index.sessions import synth_session_id
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
    return make_binding("sess-1")


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


class TestCodexReadBackDiff:
    """codex is READ-BACK: the wire correlation and the transcript adapter independently synthesize
    the session_id from the same native thread uuid, so they MUST converge (§7.2) for the pivot/diff
    to join. This proves the convergence on the synth path + the codex pivot/diff buckets."""

    async def test_codex_wire_transcript_converge_then_pivot_and_diff(
        self, conn: sqlite3.Connection
    ) -> None:
        native = (
            "019e0000-0000-7000-8000-00000000c0de"  # codex thread uuid (== rollout filename uuid)
        )
        expected = synth_session_id("run1", "codex", native)

        # WIRE (read-back): provider=codex + metadata.session_id == native → bind_exchange synthesizes.
        entry = make_index_entry(exchange_id="cx1", run_id="run1", provider="codex")
        request = make_request_ir(
            session_id=native,
            messages=[Message(role="user", content=[TextBlock(text="shared content")])],
        )
        artifacts = make_artifacts(request, make_response_ir())  # response = TextBlock("answer")
        wire_binding = bind_exchange(entry, artifacts, _run_facts())
        assert wire_binding is not None
        assert wire_binding.session_id == expected  # wire side synthesized the read-back id

        build_wire_job(entry, artifacts, wire_binding).apply(conn)

        # TRANSCRIPT (read-back): the codex adapter binds INDEPENDENTLY from the same native id and
        # MUST land on the same session_id — the §7.2 convergence the pivot depends on.
        transcript_binding = await CodexAdapter().bind(
            RunContext(
                run_id="run1",
                cwd="/w",
                workspace_slug="slug",
                workspace_hash="hash",
                cli="codex",
                started_at="t",
                native_session_id=native,
            )
        )
        assert (
            transcript_binding.session_id == wire_binding.session_id
        )  # CONVERGENCE (HARD GATE, synth)

        turn = CodexAdapter().normalize(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "shared content"},
                        {"type": "output_text", "text": "transcript only"},
                    ],
                },
            },
            TurnContext(binding=transcript_binding, source_path="rollout.jsonl", seq=0),
        )
        assert turn is not None
        build_transcript_job(turn, transcript_binding).apply(conn)

        diff = session_diff(conn, expected)
        assert _block_id(conn, "shared content") in diff.shared
        assert _block_id(conn, "transcript only") in diff.transcript_only
        assert _block_id(conn, "answer") in diff.wire_only  # the response is wire-only

        pivot = session_pivot(conn, expected)
        assert pivot == [Correspondence(exchange_id="cx1", turn_id=turn.turn_id, shared_blocks=1)]
