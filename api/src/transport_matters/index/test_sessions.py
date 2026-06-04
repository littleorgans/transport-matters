"""Session synth determinism + idempotent, COALESCE-enriching upsert (§13.1).

The canonical SessionBinding (§4.2) carries an already-resolved session_id; the wire correlation
and the transcript adapter independently produce the SAME id for a session, so upsert converges
to one row. The raw partial-unique / multiple-NULL guard is proven at the DDL level in test_schema.
"""

import uuid
from typing import TYPE_CHECKING

from transport_matters.index.adapters.base import SessionBinding
from transport_matters.index.sessions import SESSION_NS, synth_session_id, upsert_session

if TYPE_CHECKING:
    import sqlite3


def _binding(
    session_id: str, *, cli: str | None = None, provider: str = "anthropic", run: str = "run1"
) -> SessionBinding:
    return SessionBinding(
        session_id=session_id,
        provider=provider,
        run_id=run,
        cwd="/w",
        workspace_slug="slug",
        workspace_hash="hash",
        started_at="2026-06-05T00:00:00Z",
        cli=cli,
        native_session_id=session_id,
        minted=False,
    )


class TestSynth:
    def test_deterministic_uuid5(self) -> None:
        first = synth_session_id("run1", "codex", "nat-1")
        second = synth_session_id("run1", "codex", "nat-1")
        assert first == second == str(uuid.uuid5(SESSION_NS, "run1|codex|nat-1"))

    def test_distinct_inputs_yield_distinct_ids(self) -> None:
        assert synth_session_id("run1", "codex", "nat-1") != synth_session_id(
            "run1", "codex", "nat-2"
        )
        assert synth_session_id("run1", "codex", "nat-1") != synth_session_id(
            "run2", "codex", "nat-1"
        )


class TestUpsertSession:
    def test_idempotent_on_pk(self, conn: sqlite3.Connection) -> None:
        binding = _binding("sess-1", cli="claude")
        assert upsert_session(conn, binding) == upsert_session(conn, binding) == "sess-1"
        assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1

    def test_streams_converge_on_one_session_id(self, conn: sqlite3.Connection) -> None:
        # Wire (cli unknown) and transcript (cli=claude) bind the SAME native id → one row.
        assert (
            upsert_session(conn, _binding("nat-9", cli=None))
            == upsert_session(conn, _binding("nat-9", cli="claude"))
            == "nat-9"
        )
        assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1

    def test_coalesce_keeps_enrichment_across_streams(self, conn: sqlite3.Connection) -> None:
        # The transcript supplies cli=claude; a later wire upsert (cli=None) must not clobber it.
        upsert_session(conn, _binding("s1", cli="claude"))
        upsert_session(conn, _binding("s1", cli=None))
        assert (
            conn.execute("SELECT cli FROM session WHERE session_id = 's1'").fetchone()[0]
            == "claude"
        )

    def test_native_binding_records_minted_false(self, conn: sqlite3.Connection) -> None:
        upsert_session(conn, _binding("s1", cli="claude"))
        assert conn.execute("SELECT minted FROM session WHERE session_id = 's1'").fetchone()[0] == 0
