"""§3.8 executable verification reproduced against a real temp ``index.db`` (all 11 pass).

These assert the DDL contract directly via raw SQL — the value of the substrate is exact
SQL behavior (FTS, FK cascade, CHECK, partial-unique idempotency, COALESCE upsert), which a
mock would hide. The Python encoders/wrappers are proven separately in ``test_blocks.py`` /
``test_sessions.py``.
"""

import sqlite3

import pytest

from transport_matters.index.schema import apply_schema, rebuild_fts


def _upsert_block_raw(
    conn: sqlite3.Connection,
    hash_: str,
    *,
    kind: str = "text",
    text: str = "",
    identity: str = "{}",
    n_tokens: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO block (hash, kind, text, identity_canonical, n_tokens)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(hash) DO UPDATE SET n_tokens = COALESCE(excluded.n_tokens, block.n_tokens)
        """,
        (hash_, kind, text, identity, n_tokens),
    )


def _seed_block_with_edge(conn: sqlite3.Connection, *, text: str = "edged") -> int:
    _upsert_block_raw(conn, "blk-1", text=text)
    block_id = conn.execute("SELECT id FROM block WHERE hash = 'blk-1'").fetchone()[0]
    conn.execute(
        """
        INSERT INTO wire_exchange (exchange_id, run_id, provider, model, ts, raw_dir)
        VALUES ('ex1', 'run1', 'anthropic', 'claude', '2026-06-05T00:00:00.000Z', '/tmp/ex1')
        """
    )
    conn.execute(
        "INSERT INTO exchange_block (exchange_id, pos, block_id, role, section) "
        "VALUES ('ex1', 0, ?, 'assistant', 'response')",
        (block_id,),
    )
    return int(block_id)


def _insert_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    native: str | None,
    run: str = "run1",
    provider: str = "anthropic",
) -> None:
    conn.execute(
        """
        INSERT INTO session (
            session_id, provider, cli, run_id, cwd, workspace_slug, workspace_hash,
            native_session_id, minted, source_descriptor, started_at
        ) VALUES (?, ?, 'claude', ?, '/w', 'slug', 'hash', ?, 0, NULL, '2026-06-05T00:00:00Z')
        """,
        (session_id, provider, run, native),
    )


class TestSchemaDDL:
    def test_fts_virtual_table_and_triggers_created(self, conn: sqlite3.Connection) -> None:
        objs = dict(conn.execute("SELECT name, type FROM sqlite_master").fetchall())
        assert objs.get("block_fts") == "table"  # fts5 external-content virtual table
        assert objs.get("block_ai") == "trigger"
        assert objs.get("block_ad") == "trigger"
        assert "block_au" not in objs  # no update trigger by design (§3.3 immutability)

    def test_block_ai_populates_fts_and_match_finds_row(self, conn: sqlite3.Connection) -> None:
        _upsert_block_raw(conn, "h1", text="hello world")
        rows = conn.execute("SELECT rowid FROM block_fts WHERE block_fts MATCH 'hello'").fetchall()
        assert len(rows) == 1

    def test_upsert_coalesce_backfills_without_touching_identity(
        self, conn: sqlite3.Connection
    ) -> None:
        _upsert_block_raw(conn, "h1", text="t", identity="ID", n_tokens=None)
        # A re-insert sets only n_tokens; excluded text/identity are ignored.
        _upsert_block_raw(conn, "h1", text="CHANGED", identity="CHANGED", n_tokens=5)
        assert conn.execute("SELECT COUNT(*) FROM block").fetchone()[0] == 1
        text, identity, n_tokens = conn.execute(
            "SELECT text, identity_canonical, n_tokens FROM block WHERE hash = 'h1'"
        ).fetchone()
        assert (text, identity, n_tokens) == ("t", "ID", 5)
        # A later NULL must not regress the filled value (COALESCE keeps existing).
        _upsert_block_raw(conn, "h1", n_tokens=None)
        assert conn.execute("SELECT n_tokens FROM block WHERE hash = 'h1'").fetchone()[0] == 5

    def test_kind_check_rejects_out_of_enum(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            _upsert_block_raw(conn, "h1", kind="bogus")

    def test_fk_blocks_deleting_referenced_block(self, conn: sqlite3.Connection) -> None:
        block_id = _seed_block_with_edge(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM block WHERE id = ?", (block_id,))

    def test_exchange_delete_cascades_and_orphan_sweep_evicts_fts(
        self, conn: sqlite3.Connection
    ) -> None:
        _seed_block_with_edge(conn, text="orphanme")
        conn.execute("DELETE FROM wire_exchange WHERE exchange_id = 'ex1'")
        assert conn.execute("SELECT COUNT(*) FROM exchange_block").fetchone()[0] == 0
        conn.execute(
            "DELETE FROM block WHERE id NOT IN "
            "(SELECT block_id FROM exchange_block UNION SELECT block_id FROM turn_block)"
        )
        assert conn.execute("SELECT COUNT(*) FROM block").fetchone()[0] == 0
        evicted = conn.execute(
            "SELECT COUNT(*) FROM block_fts WHERE block_fts MATCH 'orphanme'"
        ).fetchone()[0]
        assert evicted == 0

    def test_session_pk_and_partial_unique_close_the_null_hole(
        self, conn: sqlite3.Connection
    ) -> None:
        _insert_session(conn, "s1", native="nat-1")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_session(conn, "s1", native="nat-1")  # duplicate session_id PK
        # Two minted rows (NULL native) with distinct session_id both insert — no false block.
        _insert_session(conn, "m1", native=None)
        _insert_session(conn, "m2", native=None)
        nulls = conn.execute(
            "SELECT COUNT(*) FROM session WHERE native_session_id IS NULL"
        ).fetchone()[0]
        assert nulls == 2
        # The partial unique index rejects two distinct ids sharing one non-null native triple.
        with pytest.raises(sqlite3.IntegrityError):
            _insert_session(conn, "s2", native="nat-1")

    def test_fts_rebuild_command_runs(self, conn: sqlite3.Connection) -> None:
        _upsert_block_raw(conn, "h1", text="rebuildable")
        rebuild_fts(conn)
        found = conn.execute(
            "SELECT COUNT(*) FROM block_fts WHERE block_fts MATCH 'rebuildable'"
        ).fetchone()[0]
        assert found == 1


class TestSchemaGate:
    def test_version_mismatch_drops_and_rebuilds(self, conn: sqlite3.Connection) -> None:
        _upsert_block_raw(conn, "keep", text="data")
        conn.execute("UPDATE schema_meta SET value = '0' WHERE key = 'adapters_version'")
        apply_schema(conn)  # gate sees the mismatch → drop + rebuild empty
        assert conn.execute("SELECT COUNT(*) FROM block").fetchone()[0] == 0
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'adapters_version'"
        ).fetchone()[0]
        assert version == "1"

    def test_matching_schema_reapply_is_idempotent(self, conn: sqlite3.Connection) -> None:
        _upsert_block_raw(conn, "keep", text="data")
        apply_schema(conn)  # no mismatch → no drop
        assert conn.execute("SELECT COUNT(*) FROM block").fetchone()[0] == 1

    def test_old_shape_with_only_schema_version_forces_rebuild(
        self, conn: sqlite3.Connection
    ) -> None:
        # A schema_meta predating the later gated keys (only schema_version present) must NOT
        # survive: each missing gated key is a mismatch, so the stale tier-2 is dropped + rebuilt
        # rather than silently re-seeded onto the old table.
        _upsert_block_raw(conn, "stale", text="old")
        conn.execute(
            "DELETE FROM schema_meta "
            "WHERE key IN ('identity_canonical', 'session_ns', 'adapters_version')"
        )
        apply_schema(conn)
        assert conn.execute("SELECT COUNT(*) FROM block").fetchone()[0] == 0
        reseeded = dict(conn.execute("SELECT key, value FROM schema_meta").fetchall())
        assert reseeded["adapters_version"] == "1"
        assert reseeded["identity_canonical"] == "identity_canonical:v1"
        assert reseeded["session_ns"]  # re-seeded
