"""Frozen row models mirror their tables (every required field maps to a column) and are immutable."""

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from transport_matters.index.adapters.base import SessionBinding
from transport_matters.index.models import SessionRow
from transport_matters.index.sessions import upsert_session

if TYPE_CHECKING:
    import sqlite3

_SESSION_COLS = [
    "session_id",
    "provider",
    "cli",
    "run_id",
    "cwd",
    "workspace_slug",
    "workspace_hash",
    "native_session_id",
    "minted",
    "source_descriptor",
    "started_at",
]


class TestRowModelsMirrorTables:
    def test_session_row_round_trips_from_select(self, conn: sqlite3.Connection) -> None:
        binding = SessionBinding(
            session_id="mint-1",
            provider="anthropic",
            run_id="run1",
            cwd="/w",
            workspace_slug="slug",
            workspace_hash="hash",
            started_at="2026-06-05T00:00:00Z",
            cli="claude",
            native_session_id="mint-1",
            minted=False,
        )
        session_id = upsert_session(conn, binding)
        record = conn.execute(
            f"SELECT {', '.join(_SESSION_COLS)} FROM session WHERE session_id = ?", (session_id,)
        ).fetchone()
        row = SessionRow(**dict(zip(_SESSION_COLS, record, strict=True)))
        assert (row.session_id, row.provider, row.minted) == (session_id, "anthropic", 0)


class TestRowModelsFrozen:
    def test_session_row_is_immutable(self) -> None:
        row = SessionRow(
            session_id="s",
            provider="anthropic",
            cli="claude",
            run_id="run1",
            cwd="/w",
            workspace_slug="slug",
            workspace_hash="hash",
            native_session_id="s",
            minted=0,
            source_descriptor=None,
            started_at="2026-06-05T00:00:00Z",
        )
        with pytest.raises(ValidationError):
            row.minted = 1  # type: ignore[misc]  # frozen models reject assignment at runtime
