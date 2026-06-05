"""§10 maintenance against a real temp ``index.db`` + seeded run dirs (never mocks; §13).

Covers the durable run enumerator (§10.1), tier-2 run/exchange delete (§10.2), and the
block GC mark-sweep (§10.3) — including the §3.3 cross-stream survival linchpin (a block
shared by a wire exchange and a transcript turn lives until BOTH refs are gone).
"""

from typing import TYPE_CHECKING

from transport_matters.index.db import transaction
from transport_matters.index.maintenance import (
    RunDir,
    delete_exchange,
    delete_run,
    gc_blocks,
    iter_run_dirs,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


# --- seed helpers (raw SQL, matching the test_schema.py convention) --------------------


def _seed_run_dir(
    root: Path, slug: str, hash_: str, run_id: str, *, index: bool = True, manifest: bool = False
) -> Path:
    """Create a ``{slug}/{hash}/{run_id}/`` dir, optionally with the durable index.jsonl
    and/or a (live-beacon) manifest.json. Returns the run dir."""
    run_dir = root / slug / hash_ / run_id
    run_dir.mkdir(parents=True)
    if index:
        (run_dir / "index.jsonl").write_text("{}\n")
    if manifest:
        (run_dir / "manifest.json").write_text("{}")
    return run_dir


def _seed_block(conn: sqlite3.Connection, hash_: str, *, text: str = "body") -> int:
    conn.execute(
        "INSERT INTO block (hash, kind, text, identity_canonical) VALUES (?, 'text', ?, '{}')",
        (hash_, text),
    )
    return int(conn.execute("SELECT id FROM block WHERE hash = ?", (hash_,)).fetchone()[0])


def _seed_session(conn: sqlite3.Connection, session_id: str, *, run_id: str) -> None:
    conn.execute(
        """
        INSERT INTO session (
            session_id, provider, cli, run_id, cwd, workspace_slug, workspace_hash,
            native_session_id, minted, source_descriptor, started_at
        ) VALUES (?, 'anthropic', 'claude', ?, '/w', 'slug', 'hash', NULL, 0, NULL, 't')
        """,
        (session_id, run_id),
    )


def _seed_exchange(conn: sqlite3.Connection, exchange_id: str, *, run_id: str) -> None:
    conn.execute(
        """
        INSERT INTO wire_exchange (exchange_id, run_id, provider, model, ts, raw_dir)
        VALUES (?, ?, 'anthropic', 'claude', '2026-06-05T00:00:00.000Z', '/tmp/x')
        """,
        (exchange_id, run_id),
    )


def _seed_turn(conn: sqlite3.Connection, turn_id: str, *, session_id: str, run_id: str) -> None:
    conn.execute(
        """
        INSERT INTO transcript_turn (turn_id, session_id, run_id, provider, cli, role, seq, source_path)
        VALUES (?, ?, ?, 'anthropic', 'claude', 'assistant', 0, '/s.jsonl')
        """,
        (turn_id, session_id, run_id),
    )


def _link_exchange_block(
    conn: sqlite3.Connection, exchange_id: str, block_id: int, pos: int
) -> None:
    conn.execute(
        "INSERT INTO exchange_block (exchange_id, pos, block_id, role, section) "
        "VALUES (?, ?, ?, 'assistant', 'response')",
        (exchange_id, pos, block_id),
    )


def _link_turn_block(conn: sqlite3.Connection, turn_id: str, block_id: int, pos: int) -> None:
    conn.execute(
        "INSERT INTO turn_block (turn_id, pos, block_id, role) VALUES (?, ?, ?, 'assistant')",
        (turn_id, pos, block_id),
    )


def _count(conn: sqlite3.Connection, sql: str, *params: object) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


# --- iter_run_dirs (§10.1 durable enumerator) ------------------------------------------


class TestIterRunDirs:
    def test_yields_index_bearing_dirs_with_root_and_run_id(self, tmp_path: Path) -> None:
        a = _seed_run_dir(tmp_path, "proj", "h1", "run-a")
        b = _seed_run_dir(tmp_path, "proj", "h2", "run-b")
        found = sorted(iter_run_dirs(tmp_path), key=lambda r: r.run_id)
        assert found == [RunDir(root=a, run_id="run-a"), RunDir(root=b, run_id="run-b")]

    def test_durable_run_found_without_a_manifest(self, tmp_path: Path) -> None:
        # A completed run (post-exit) has NO manifest — its unlink is the §10.1 beacon teardown.
        _seed_run_dir(tmp_path, "proj", "h1", "done", index=True, manifest=False)
        assert [r.run_id for r in iter_run_dirs(tmp_path)] == ["done"]

    def test_manifest_only_dir_is_ignored(self, tmp_path: Path) -> None:
        # The peer-blocked beacon bug: a live manifest with NO index.jsonl captured nothing,
        # so it must NOT be enumerated. Durability is keyed on index.jsonl, not manifest.json.
        _seed_run_dir(tmp_path, "proj", "h1", "captured", index=True, manifest=True)
        _seed_run_dir(tmp_path, "proj", "h2", "live-empty", index=False, manifest=True)
        assert [r.run_id for r in iter_run_dirs(tmp_path)] == ["captured"]

    def test_missing_root_yields_nothing(self, tmp_path: Path) -> None:
        assert list(iter_run_dirs(tmp_path / "nope")) == []


# --- delete_run / delete_exchange (§10.2) ----------------------------------------------


class TestDeleteRun:
    def test_removes_entities_and_cascades_edges_leaving_other_run(
        self, conn: sqlite3.Connection
    ) -> None:
        blk = _seed_block(conn, "shared")
        for run, ex, sess, turn in (("run1", "ex1", "s1", "t1"), ("run2", "ex2", "s2", "t2")):
            _seed_session(conn, sess, run_id=run)
            _seed_exchange(conn, ex, run_id=run)
            _seed_turn(conn, turn, session_id=sess, run_id=run)
            _link_exchange_block(conn, ex, blk, 0)
            _link_turn_block(conn, turn, blk, 0)

        with transaction(conn):
            delete_run(conn, "run1")

        # run1 entities + their edges are gone (edges via ON DELETE CASCADE).
        assert _count(conn, "SELECT COUNT(*) FROM wire_exchange WHERE run_id='run1'") == 0
        assert _count(conn, "SELECT COUNT(*) FROM transcript_turn WHERE run_id='run1'") == 0
        assert _count(conn, "SELECT COUNT(*) FROM session WHERE run_id='run1'") == 0
        assert _count(conn, "SELECT COUNT(*) FROM exchange_block WHERE exchange_id='ex1'") == 0
        assert _count(conn, "SELECT COUNT(*) FROM turn_block WHERE turn_id='t1'") == 0
        # run2 is untouched.
        assert _count(conn, "SELECT COUNT(*) FROM wire_exchange WHERE run_id='run2'") == 1
        assert _count(conn, "SELECT COUNT(*) FROM transcript_turn WHERE run_id='run2'") == 1
        assert _count(conn, "SELECT COUNT(*) FROM session WHERE run_id='run2'") == 1
        # blocks are global — never touched by delete (reclaimed only by gc_blocks).
        assert _count(conn, "SELECT COUNT(*) FROM block") == 1

    def test_does_not_touch_tier1_raw_dir(self, conn: sqlite3.Connection, tmp_path: Path) -> None:
        # Contract (§10.2): delete_run is tier-2-only. Tier-1 deletion is the storage layer's
        # job (disk.py:265 async delete_exchange / staged-delete). Maintenance never unlinks tier-1.
        raw_dir = _seed_run_dir(tmp_path, "proj", "h1", "run1")
        _seed_exchange(conn, "ex1", run_id="run1")
        with transaction(conn):
            delete_run(conn, "run1")
        assert raw_dir.exists()
        assert (raw_dir / "index.jsonl").exists()


class TestDeleteExchange:
    def test_removes_one_exchange_and_shared_block_survives(self, conn: sqlite3.Connection) -> None:
        blk = _seed_block(conn, "shared")
        _seed_exchange(conn, "ex1", run_id="run1")
        _seed_exchange(conn, "ex2", run_id="run1")
        _link_exchange_block(conn, "ex1", blk, 0)
        _link_exchange_block(conn, "ex2", blk, 0)

        with transaction(conn):
            delete_exchange(conn, "ex1")

        assert _count(conn, "SELECT COUNT(*) FROM wire_exchange WHERE exchange_id='ex1'") == 0
        assert _count(conn, "SELECT COUNT(*) FROM exchange_block WHERE exchange_id='ex1'") == 0
        assert _count(conn, "SELECT COUNT(*) FROM wire_exchange WHERE exchange_id='ex2'") == 1
        # The block is still referenced by ex2 → it survives (GC reclaims only orphans).
        assert _count(conn, "SELECT COUNT(*) FROM block WHERE id=?", blk) == 1


# --- gc_blocks (§10.3 mark-sweep) ------------------------------------------------------


class TestGcBlocks:
    def test_sweeps_only_unreferenced_and_evicts_fts(self, conn: sqlite3.Connection) -> None:
        referenced = _seed_block(conn, "kept", text="kept text")
        _seed_exchange(conn, "ex1", run_id="run1")
        _link_exchange_block(conn, "ex1", referenced, 0)
        orphan = _seed_block(conn, "orphan", text="orphanme")

        with transaction(conn):
            swept = gc_blocks(conn)

        assert swept == 1
        assert _count(conn, "SELECT COUNT(*) FROM block WHERE id=?", orphan) == 0
        assert _count(conn, "SELECT COUNT(*) FROM block WHERE id=?", referenced) == 1
        # block_ad trigger evicted the orphan's FTS row; the kept block's row survives.
        assert _count(conn, "SELECT COUNT(*) FROM block_fts WHERE block_fts MATCH 'orphanme'") == 0
        assert _count(conn, "SELECT COUNT(*) FROM block_fts WHERE block_fts MATCH 'kept'") == 1

    def test_is_idempotent(self, conn: sqlite3.Connection) -> None:
        _seed_block(conn, "orphan", text="x")
        with transaction(conn):
            first = gc_blocks(conn)
        with transaction(conn):
            second = gc_blocks(conn)
        assert (first, second) == (1, 0)
        assert _count(conn, "SELECT COUNT(*) FROM block") == 0

    def test_cross_stream_block_survives_until_both_refs_gone(
        self, conn: sqlite3.Connection
    ) -> None:
        # The §3.3 dedup linchpin: one block referenced by BOTH a wire exchange and a transcript
        # turn must not be reclaimed while EITHER edge survives — the predicate checks both tables.
        blk = _seed_block(conn, "dual", text="dual")
        _seed_session(conn, "s1", run_id="run1")
        _seed_exchange(conn, "ex1", run_id="run1")
        _seed_turn(conn, "t1", session_id="s1", run_id="run1")
        _link_exchange_block(conn, "ex1", blk, 0)
        _link_turn_block(conn, "t1", blk, 0)

        # Both refs present → GC is a no-op.
        with transaction(conn):
            assert gc_blocks(conn) == 0
        assert _count(conn, "SELECT COUNT(*) FROM block WHERE id=?", blk) == 1

        # Drop the wire ref → still held by the turn → still survives.
        with transaction(conn):
            delete_exchange(conn, "ex1")
            assert gc_blocks(conn) == 0
        assert _count(conn, "SELECT COUNT(*) FROM block WHERE id=?", blk) == 1

        # Drop the turn ref too → now unreferenced by both → swept.
        with transaction(conn):
            delete_run(conn, "run1")
            assert gc_blocks(conn) == 1
        assert _count(conn, "SELECT COUNT(*) FROM block WHERE id=?", blk) == 0
