"""§10.5 / §11.2 replay: rebuild tier-2 from tier-1 alone — backfill, reconcile, idempotence, demo.

Real temp SQLite + seeded run dirs (never mocks; §13). A run dir is seeded with exactly what tier-1
holds — ``index.jsonl`` + ``*.ir.json`` (wire), ``transcripts/<sid>.jsonl`` (the 8b-i snapshot), and
``sessions.json`` (the 8b-ii owned facts) — and replayed through the real writer. The killer-demo
test proves the payoff: a session whose CLI transcript file is GONE still rebuilds, byte-identically,
from the snapshot.
"""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from transport_matters import manifest
from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
)
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.db import connect
from transport_matters.index.ingest import RunFacts, make_index_sink
from transport_matters.index.maintenance import iter_run_dirs
from transport_matters.index.queries import session_diff
from transport_matters.index.rebuild import backfill, rebuild, reconcile, replay_run
from transport_matters.index.schema import apply_schema
from transport_matters.index.tailer import TailCursor, TranscriptTailer
from transport_matters.index.test_replay_support import (
    _HASH,
    _SLUG,
    _counts,
    _descriptor,
    _drain,
    _run_dir,
    _seed_claude_run,
    _seed_codex_run,
    _write_wire,
)
from transport_matters.ir import Message, SystemPart, TextBlock
from transport_matters.storage.test_exchange_support import (
    make_artifacts,
    make_index_entry,
    make_request_ir,
    make_response_ir,
)

if TYPE_CHECKING:
    import sqlite3

    from transport_matters.storage.base import ExchangeArtifacts, IndexEntry


def _diff_hashes(conn: sqlite3.Connection, sid: str) -> dict[str, list[str]]:
    """The §8.4 diff translated from (DB-local) block ids to (content-stable) block hashes."""
    diff = session_diff(conn, sid)

    def to_hashes(ids: list[int]) -> list[str]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT hash FROM block WHERE id IN ({placeholders})", ids).fetchall()
        return sorted(row[0] for row in rows)

    return {bucket: to_hashes(ids) for bucket, ids in vars(diff).items()}


# ── replay_run: rebuild one run from tier-1 alone ──────────────────────────────────────────


class TestReplayRun:
    def test_rebuilds_wire_and_transcript_from_tier1(self, tmp_path: Path) -> None:
        sid = "00000000-0000-4000-8000-000000000001"
        _seed_claude_run(tmp_path, "run1", sid)
        db = tmp_path / "index.db"
        writer = _drain(db)
        replay_run(writer, next(iter(iter_run_dirs(tmp_path))))
        writer.stop(drain=True)

        conn = connect(db)
        try:
            assert _counts(conn)["wire_exchange"] == 1
            turns = conn.execute(
                "SELECT turn_id, seq, role, parent_id FROM transcript_turn "
                "WHERE session_id = ? ORDER BY seq",
                (sid,),
            ).fetchall()
            assert turns == [("u1", 0, "user", None), ("a1", 1, "assistant", "u1")]
            # The session row was created by both streams, keyed on the same minted session_id.
            assert conn.execute(
                "SELECT minted, cli FROM session WHERE session_id = ?", (sid,)
            ).fetchone() == (1, "claude")
            # Cross-stream dedup survived: the wire response and the assistant turn share one block.
            assert _diff_hashes(conn, sid)["shared"]
        finally:
            conn.close()

    def test_rebuilds_readback_codex_with_synth_session_id(self, tmp_path: Path) -> None:
        # The read-back path the reviewer flags: codex is minted=False, so the wire correlation and
        # the transcript both resolve session_id = synth(run_id, "codex", native) and the snapshot is
        # keyed by that synth id. Replay must reconstruct it from sessions.json identically or the
        # pivot join silently empties.
        native = "rollout-native-7"
        session_id = _seed_codex_run(tmp_path, "run1", native)
        db = tmp_path / "index.db"
        writer = _drain(db)
        replay_run(writer, next(iter(iter_run_dirs(tmp_path))))
        writer.stop(drain=True)

        conn = connect(db)
        try:
            # Wire and transcript converged on the SAME synth session_id (the pivot linchpin).
            assert (
                conn.execute(
                    "SELECT session_id FROM wire_exchange WHERE run_id = 'run1'"
                ).fetchone()[0]
                == session_id
            )
            turns = conn.execute(
                "SELECT session_id, role FROM transcript_turn WHERE run_id = 'run1' ORDER BY seq"
            ).fetchall()
            assert turns == [(session_id, "assistant")]  # session_meta skipped, response_item kept
            assert conn.execute(
                "SELECT minted, cli, native_session_id FROM session WHERE session_id = ?",
                (session_id,),
            ).fetchone() == (0, "codex", native)
        finally:
            conn.close()

    def test_idempotent_second_replay_adds_no_rows(self, tmp_path: Path) -> None:
        sid = "00000000-0000-4000-8000-000000000002"
        _seed_claude_run(tmp_path, "run1", sid)
        db = tmp_path / "index.db"
        run_dir = next(iter(iter_run_dirs(tmp_path)))

        first = _drain(db)
        replay_run(first, run_dir)
        first.stop(drain=True)
        conn = connect(db)
        try:
            before = _counts(conn)
        finally:
            conn.close()

        second = _drain(db)
        replay_run(second, run_dir)
        second.stop(drain=True)
        conn = connect(db)
        try:
            assert _counts(conn) == before  # upserts dedup; identical content rehashes to one block
        finally:
            conn.close()


# ── backfill / reconcile ───────────────────────────────────────────────────────────────────


class TestBackfill:
    def test_backfills_every_run_dir(self, tmp_path: Path) -> None:
        _seed_claude_run(tmp_path, "run1", "00000000-0000-4000-8000-00000000000a")
        _seed_claude_run(tmp_path, "run2", "00000000-0000-4000-8000-00000000000b")
        db = tmp_path / "index.db"
        writer = _drain(db)
        backfill(writer, tmp_path)
        writer.stop(drain=True)

        conn = connect(db)
        try:
            assert {
                row[0] for row in conn.execute("SELECT DISTINCT run_id FROM wire_exchange")
            } == {
                "run1",
                "run2",
            }
        finally:
            conn.close()

    def test_backfills_single_run_id(self, tmp_path: Path) -> None:
        _seed_claude_run(tmp_path, "run1", "00000000-0000-4000-8000-00000000000c")
        _seed_claude_run(tmp_path, "run2", "00000000-0000-4000-8000-00000000000d")
        db = tmp_path / "index.db"
        writer = _drain(db)
        backfill(writer, tmp_path, run_id="run2")
        writer.stop(drain=True)

        conn = connect(db)
        try:
            assert {
                row[0] for row in conn.execute("SELECT DISTINCT run_id FROM wire_exchange")
            } == {"run2"}
        finally:
            conn.close()


class TestReconcile:
    def test_replays_undercounted_run(self, tmp_path: Path) -> None:
        # §10.4 under-count repair: a run already in tier-2 but with FEWER wire rows than its tier-1
        # index (a §6.3 backpressure drop) must be replayed, not skipped. Seed one exchange, index it,
        # then append a second exchange to tier-1 only → tier-1=2, tier-2=1 → reconcile fills the gap.
        root = _run_dir(tmp_path, "run1")
        _write_wire(root, *_uncounted_exchange("ex1"))
        db = tmp_path / "index.db"
        seed = _drain(db)
        backfill(seed, tmp_path)
        seed.stop(drain=True)
        conn = connect(db)
        try:
            assert (
                conn.execute("SELECT COUNT(*) FROM wire_exchange WHERE run_id = 'run1'").fetchone()[
                    0
                ]
                == 1
            )  # tier-2 under-counts the run after the first pass
        finally:
            conn.close()

        _write_wire(root, *_uncounted_exchange("ex2"))  # tier-1 now holds 2, tier-2 still 1
        reader = connect(db)
        writer = _drain(db)
        try:
            reconcile(writer, reader, tmp_path)
        finally:
            writer.stop(drain=True)
            reader.close()

        conn = connect(db)
        try:
            assert (
                conn.execute("SELECT COUNT(*) FROM wire_exchange WHERE run_id = 'run1'").fetchone()[
                    0
                ]
                == 2
            )  # under-counted run replayed → tier-2 matches tier-1
        finally:
            conn.close()

    def test_backfills_missing_and_evicts_orphan(self, tmp_path: Path) -> None:
        # run1 is on disk only (missing from tier-2 → backfill); run-orphan is in tier-2 only
        # (its dir was rm -rf'd → evict + GC). Build tier-2 with the orphan first, then delete its dir.
        _seed_claude_run(tmp_path, "run-orphan", "00000000-0000-4000-8000-00000000000e")
        seed = _drain(tmp_path / "index.db")
        backfill(seed, tmp_path, run_id="run-orphan")
        seed.stop(drain=True)
        shutil.rmtree(tmp_path / _SLUG / _HASH / "run-orphan")

        _seed_claude_run(tmp_path, "run1", "00000000-0000-4000-8000-00000000000f")
        reader = connect(tmp_path / "index.db")
        writer = _drain(tmp_path / "index.db")
        try:
            reconcile(writer, reader, tmp_path)
        finally:
            writer.stop(drain=True)
            reader.close()

        conn = connect(tmp_path / "index.db")
        try:
            runs = {row[0] for row in conn.execute("SELECT DISTINCT run_id FROM wire_exchange")}
            assert runs == {"run1"}  # orphan evicted, missing backfilled
            # GC reclaimed the orphan's now-unreferenced blocks (no dangling rows).
            assert (
                conn.execute("SELECT COUNT(*) FROM session WHERE run_id = 'run-orphan'").fetchone()[
                    0
                ]
                == 0
            )
        finally:
            conn.close()

    def test_skips_live_run_in_both_directions(self, tmp_path: Path) -> None:
        # A run with a present (live) manifest is mid-flight: never backfill it (a live writer owns it)
        # and never evict it. Seed it on disk with a manifest but NOT in tier-2 → reconcile must skip.
        root, _ = _seed_claude_run(tmp_path, "live-run", "00000000-0000-4000-8000-000000000010")
        manifest.write(root / "manifest.json", _manifest("live-run", root))

        reader = connect(tmp_path / "index.db")
        apply_schema(
            reader
        )  # reconcile reads an already-initialized tier-2 (load_runtime applies it)
        writer = _drain(tmp_path / "index.db")
        try:
            reconcile(writer, reader, tmp_path)
        finally:
            writer.stop(drain=True)
            reader.close()

        conn = connect(tmp_path / "index.db")
        try:
            assert conn.execute("SELECT COUNT(*) FROM wire_exchange").fetchone()[0] == 0
        finally:
            conn.close()


# ── the killer demo: rebuild == live, with the CLI transcript file gone ─────────────────────


class TestKillerDemo:
    def test_rebuild_matches_live_after_cli_file_deleted(self, tmp_path: Path) -> None:
        sid = "00000000-0000-4000-8000-000000000011"
        run_id = "run1"
        _root, cli_path = _seed_claude_run(tmp_path, run_id, sid)

        # ── LIVE: wire via the post-persist sink, transcript via the tailer over the CLI file. ──
        live_db = tmp_path / "live.db"
        writer = _drain(live_db)
        sink = make_index_sink(writer, _live_run_facts(run_id, sid, cli_path))
        entry, artifacts = _exchange(sid, run_id)
        sink(entry, artifacts)
        tailer = TranscriptTailer(writer.submit)
        tailer.register(
            TailCursor(
                binding=_live_transcript_binding(run_id, sid, cli_path),
                source=FileTailSource(path=str(cli_path), format="claude_jsonl"),
                adapter=ClaudeAdapter(),
            )
        )
        tailer.poll()
        writer.stop(drain=True)

        live = connect(live_db)
        try:
            live_diff = _diff_hashes(live, sid)
            live_turns = _turn_fingerprint(live, sid)
            live_counts = _counts(live)
        finally:
            live.close()

        # ── The CLI file vanishes (claude GC'd it / a fresh box) — tier-1 still owns the snapshot. ──
        cli_path.unlink()
        assert not cli_path.exists()

        # ── REBUILD: drop nothing (fresh db), replay every run dir from tier-1 alone. ──
        rebuilt_db = tmp_path / "rebuilt.db"
        rebuild(tmp_path, db_path=rebuilt_db)

        rebuilt = connect(rebuilt_db)
        try:
            assert (
                _turn_fingerprint(rebuilt, sid) == live_turns
            )  # same turns, replayed from snapshot
            assert (
                _diff_hashes(rebuilt, sid) == live_diff
            )  # block hashes match → DIFF byte-identical
            assert _counts(rebuilt) == live_counts
            assert live_diff["shared"]  # the session whose CLI file is gone still correlates
            # The recorded source_path is the (now-absent) CLI path — replay read the snapshot, not it.
            assert _source_path(rebuilt, sid) == str(cli_path)
        finally:
            rebuilt.close()


# ── small test-local builders ───────────────────────────────────────────────────────────────


def _exchange(sid: str, run_id: str) -> tuple[IndexEntry, ExchangeArtifacts]:
    request = make_request_ir(
        session_id=sid,
        system=[SystemPart(text="sys")],
        messages=[Message(role="user", content=[TextBlock(text="ask")])],
    )
    entry = make_index_entry(exchange_id=f"{run_id}-ex1", run_id=run_id, provider="anthropic")
    return entry, make_artifacts(request, make_response_ir())


def _uncounted_exchange(exchange_id: str) -> tuple[IndexEntry, ExchangeArtifacts]:
    """A distinct wire exchange under one session, for the §10.4 under-count regression."""
    request = make_request_ir(
        session_id="s-uc", messages=[Message(role="user", content=[TextBlock(text=exchange_id)])]
    )
    entry = make_index_entry(exchange_id=exchange_id, run_id="run1", provider="anthropic")
    return entry, make_artifacts(request)


def _live_run_facts(run_id: str, sid: str, cli_path: Path) -> RunFacts:
    return RunFacts(
        run_id=run_id,
        cwd=Path("/w"),
        workspace_slug=_SLUG,
        workspace_hash=_HASH,
        started_at="2026-06-05T12:00:00+00:00",
        cli="claude",
        owned_native_session_id=sid,
        owned_source_descriptor=_descriptor(cli_path),
    )


def _live_transcript_binding(run_id: str, sid: str, cli_path: Path) -> SessionBinding:
    return SessionBinding(
        session_id=sid,
        provider="anthropic",
        run_id=run_id,
        cwd="/w",
        workspace_slug=_SLUG,
        workspace_hash=_HASH,
        started_at="2026-06-05T12:00:00+00:00",
        cli="claude",
        native_session_id=sid,
        minted=True,
        source_descriptor=_descriptor(cli_path),
    )


def _turn_fingerprint(conn: sqlite3.Connection, sid: str) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT turn_id, seq, role, parent_id, source_path FROM transcript_turn "
        "WHERE session_id = ? ORDER BY seq",
        (sid,),
    ).fetchall()


def _source_path(conn: sqlite3.Connection, sid: str) -> str:
    row = conn.execute(
        "SELECT source_path FROM transcript_turn WHERE session_id = ? ORDER BY seq LIMIT 1",
        (sid,),
    ).fetchone()
    return str(row[0])


def _manifest(run_id: str, root: Path) -> manifest.Manifest:
    return manifest.Manifest(
        cwd="/w",
        pid=1234,
        proxy_port=1,
        web_port=2,
        storage_dir=str(root),
        run_id=run_id,
        started_at="2026-06-05T12:00:00+00:00",
        transport_matters_version="0.0.0",
        slug=_SLUG,
        hash=_HASH,
    )
