"""Session synth determinism, binding resolution, and idempotent upsert (§13.1).

The raw partial-unique / multiple-NULL guard is proven at the DDL level in ``test_schema.py``;
here we prove the Python surface: deterministic synth, minted-vs-readback resolution, PK-keyed
idempotency, and that both streams converge on one ``session_id``.
"""

import uuid
from typing import TYPE_CHECKING

import pytest

from transport_matters.index.sessions import (
    SESSION_NS,
    SessionBinding,
    resolve_session_id,
    synth_session_id,
    upsert_session,
)

if TYPE_CHECKING:
    import sqlite3


def _readback(native: str, *, run: str = "run1", provider: str = "codex") -> SessionBinding:
    return SessionBinding(
        provider=provider,
        run_id=run,
        cwd="/w",
        workspace_slug="slug",
        workspace_hash="hash",
        started_at="2026-06-05T00:00:00Z",
        cli="codex",
        native_session_id=native,
    )


def _minted(mint: str) -> SessionBinding:
    return SessionBinding(
        provider="anthropic",
        run_id="run1",
        cwd="/w",
        workspace_slug="slug",
        workspace_hash="hash",
        started_at="2026-06-05T00:00:00Z",
        cli="claude",
        minted_session_id=mint,
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


class TestResolve:
    def test_minted_passthrough(self) -> None:
        assert resolve_session_id(_minted("mint-123")) == "mint-123"

    def test_readback_synth(self) -> None:
        binding = _readback("nat-1")
        assert resolve_session_id(binding) == synth_session_id("run1", "codex", "nat-1")

    def test_requires_native_or_minted(self) -> None:
        bare = SessionBinding(
            provider="codex",
            run_id="r",
            cwd="/w",
            workspace_slug="s",
            workspace_hash="h",
            started_at="t",
        )
        with pytest.raises(ValueError, match="native_session_id or minted"):
            resolve_session_id(bare)


class TestUpsertSession:
    def test_idempotent_on_pk(self, conn: sqlite3.Connection) -> None:
        binding = _readback("nat-1")
        assert upsert_session(conn, binding) == upsert_session(conn, binding)
        assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1

    def test_minted_nulls_allow_multiple_rows(self, conn: sqlite3.Connection) -> None:
        upsert_session(conn, _minted("mint-1"))
        upsert_session(conn, _minted("mint-2"))
        nulls = conn.execute(
            "SELECT COUNT(*) FROM session WHERE native_session_id IS NULL"
        ).fetchone()[0]
        assert nulls == 2

    def test_streams_converge_on_one_session_id(self, conn: sqlite3.Connection) -> None:
        # The wire correlation and the transcript adapter independently bind the same triple.
        wire = _readback("nat-9")
        transcript = _readback("nat-9")
        assert upsert_session(conn, wire) == upsert_session(conn, transcript)
        assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1

    def test_minted_flag_recorded(self, conn: sqlite3.Connection) -> None:
        session_id = upsert_session(conn, _minted("mint-1"))
        minted = conn.execute(
            "SELECT minted FROM session WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        assert minted == 1
