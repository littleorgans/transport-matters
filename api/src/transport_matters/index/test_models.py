"""Frozen row models mirror their tables (every required field maps to a column) and are immutable."""

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from transport_matters.index.blocks import upsert_block
from transport_matters.index.models import BlockRow, SessionRow
from transport_matters.index.sessions import SessionBinding, upsert_session
from transport_matters.ir import TextBlock

if TYPE_CHECKING:
    import sqlite3

_BLOCK_COLS = ["id", "hash", "kind", "text", "identity_canonical", "n_tokens", "created_at"]
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
    def test_block_row_round_trips_from_select(self, conn: sqlite3.Connection) -> None:
        block_id = upsert_block(conn, TextBlock(text="x"), n_tokens=3)
        record = conn.execute(
            f"SELECT {', '.join(_BLOCK_COLS)} FROM block WHERE id = ?", (block_id,)
        ).fetchone()
        row = BlockRow(**dict(zip(_BLOCK_COLS, record, strict=True)))
        assert (row.id, row.kind, row.text, row.n_tokens) == (block_id, "text", "x", 3)

    def test_session_row_round_trips_from_select(self, conn: sqlite3.Connection) -> None:
        binding = SessionBinding(
            provider="anthropic",
            run_id="run1",
            cwd="/w",
            workspace_slug="slug",
            workspace_hash="hash",
            started_at="2026-06-05T00:00:00Z",
            cli="claude",
            minted_session_id="mint-1",
        )
        session_id = upsert_session(conn, binding)
        record = conn.execute(
            f"SELECT {', '.join(_SESSION_COLS)} FROM session WHERE session_id = ?", (session_id,)
        ).fetchone()
        row = SessionRow(**dict(zip(_SESSION_COLS, record, strict=True)))
        assert (row.session_id, row.provider, row.minted) == (session_id, "anthropic", 1)


class TestRowModelsFrozen:
    def test_block_row_is_immutable(self) -> None:
        row = BlockRow(
            id=1,
            hash="h",
            kind="text",
            text="t",
            identity_canonical="c",
            n_tokens=None,
            created_at="2026-06-05T00:00:00Z",
        )
        with pytest.raises(ValidationError):
            row.n_tokens = 5  # type: ignore[misc]  # frozen models reject assignment at runtime
