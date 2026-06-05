"""§10.5 / §11.2 replay: rebuild tier-2 from tier-1 alone — backfill, reconcile, idempotence, demo.

Real temp SQLite + seeded run dirs (never mocks; §13). A run dir is seeded with exactly what tier-1
holds — ``index.jsonl`` + ``*.ir.json`` (wire), ``transcripts/<sid>.jsonl`` (the 8b-i snapshot), and
``sessions.json`` (the 8b-ii owned facts) — and replayed through the real writer. The killer-demo
test proves the payoff: a session whose CLI transcript file is GONE still rebuilds, byte-identically,
from the snapshot.
"""

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from transport_matters import manifest
from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
    encode_source_descriptor,
)
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.db import connect
from transport_matters.index.ingest import RunFacts, make_index_sink
from transport_matters.index.maintenance import iter_run_dirs
from transport_matters.index.queries import session_diff
from transport_matters.index.rebuild import backfill, rebuild, reconcile, replay_run
from transport_matters.index.schema import apply_schema
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.tailer import TailCursor, TranscriptTailer
from transport_matters.index.writer import IndexWriter
from transport_matters.ir import Message, SystemPart, TextBlock
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.session_facts import OwnedSessionFacts, write_owned_session_facts
from transport_matters.storage.test_exchange_support import (
    make_artifacts,
    make_index_entry,
    make_request_ir,
    make_response_ir,
)

if TYPE_CHECKING:
    import sqlite3

    from transport_matters.storage.base import ExchangeArtifacts, IndexEntry

_SLUG = "proj"
_HASH = "h1"


# ── seed helpers ─────────────────────────────────────────────────────────────────────────


def _run_dir(workspaces_root: Path, run_id: str) -> Path:
    root = workspaces_root / _SLUG / _HASH / run_id
    root.mkdir(parents=True)
    return root


def _write_wire(root: Path, entry: IndexEntry, artifacts: ExchangeArtifacts) -> None:
    """Persist one exchange the way the recorder does: an ``index.jsonl`` line + IR artifacts."""
    layout = DiskStorageLayout(root)
    with layout.index_path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")
    exchange_dir = layout.new_exchange_dir(entry.id, now=entry.ts)
    exchange_dir.mkdir(parents=True, exist_ok=True)
    paths = layout.artifact_paths(exchange_dir)
    paths.request_ir.write_text(artifacts.request_ir.model_dump_json(), encoding="utf-8")
    if artifacts.response_ir is not None:
        paths.response_ir.write_text(artifacts.response_ir.model_dump_json(), encoding="utf-8")


def _claude_user(uuid: str, text: str, sid: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "uuid": uuid,
            "parentUuid": None,
            "sessionId": sid,
            "isSidechain": False,
            "timestamp": "2026-06-05T12:00:00Z",
            "message": {"role": "user", "content": text},
        }
    )


def _claude_assistant(uuid: str, parent: str, text: str, sid: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "uuid": uuid,
            "parentUuid": parent,
            "sessionId": sid,
            "isSidechain": False,
            "timestamp": "2026-06-05T12:00:01Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }
    )


def _descriptor(path: Path) -> str:
    return encode_source_descriptor(FileTailSource(path=str(path), format="claude_jsonl"))


def _codex_session_meta(native: str) -> str:
    return json.dumps({"type": "session_meta", "payload": {"id": native, "cwd": "/w"}})


def _codex_response_item(text: str) -> str:
    return json.dumps(
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
        }
    )


def _seed_codex_run(workspaces_root: Path, run_id: str, native: str) -> str:
    """Seed an owned-codex run (read-back synth PK); return the synthesized ``session_id``.

    codex is ``minted=False``: the session_id is ``synth_session_id(run_id, "codex", native)`` on
    BOTH streams, and the snapshot is keyed by that synth id — so a faithful rebuild must reconstruct
    it from ``sessions.json`` the same way (the explicit reviewer check for the read-back path).
    """
    session_id = synth_session_id(run_id, "codex", native)
    root = _run_dir(workspaces_root, run_id)
    request = make_request_ir(
        session_id=native, messages=[Message(role="user", content=[TextBlock(text="ask")])]
    )
    entry = make_index_entry(exchange_id=f"{run_id}-ex1", run_id=run_id, provider="codex")
    _write_wire(root, entry, make_artifacts(request, make_response_ir()))

    snapshot = _codex_session_meta(native) + "\n" + _codex_response_item("codex answer") + "\n"
    snapshot_path = DiskStorageLayout(root).transcript_snapshot_path(session_id)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(snapshot, encoding="utf-8")

    rollout = root / "rollout.jsonl"  # the descriptor target — never read by replay (snapshot wins)
    descriptor = encode_source_descriptor(FileTailSource(path=str(rollout), format="codex_rollout"))
    write_owned_session_facts(
        root,
        OwnedSessionFacts(
            run_id=run_id,
            cli="codex",
            native_session_id=native,
            minted=False,
            source_descriptor=descriptor,
        ),
    )
    return session_id


def _seed_claude_run(
    workspaces_root: Path, run_id: str, sid: str, *, write_cli_file: bool = True
) -> tuple[Path, Path]:
    """Seed a complete owned-claude run dir; return ``(root, cli_path)``.

    Wire: one anthropic exchange whose response shares ``"answer"`` with the transcript (so the diff
    has a real ``shared`` bucket — the cross-stream dedup linchpin). Transcript snapshot: a user turn
    (``"hi"`` — transcript_only) + an assistant turn (``"answer"`` — shared). The CLI source file (the
    descriptor target) is written only when *write_cli_file* — the killer demo deletes it.
    """
    root = _run_dir(workspaces_root, run_id)
    request = make_request_ir(
        session_id=sid,
        system=[SystemPart(text="sys")],
        messages=[Message(role="user", content=[TextBlock(text="ask")])],
    )
    entry = make_index_entry(exchange_id=f"{run_id}-ex1", run_id=run_id, provider="anthropic")
    _write_wire(root, entry, make_artifacts(request, make_response_ir()))

    snapshot = _claude_user("u1", "hi", sid) + "\n" + _claude_assistant("a1", "u1", "answer", sid)
    snapshot += "\n"
    snapshot_path = DiskStorageLayout(root).transcript_snapshot_path(sid)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(snapshot, encoding="utf-8")

    cli_path = root / "cli.jsonl"
    if write_cli_file:
        cli_path.write_text(snapshot, encoding="utf-8")
    write_owned_session_facts(
        root,
        OwnedSessionFacts(
            run_id=run_id,
            cli="claude",
            native_session_id=sid,
            minted=True,
            source_descriptor=_descriptor(cli_path),
        ),
    )
    return root, cli_path


def _drain(db_path: Path) -> IndexWriter:
    writer = IndexWriter(str(db_path), flush_ms=5)
    writer.start()
    return writer


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "session",
        "wire_exchange",
        "transcript_turn",
        "block",
        "exchange_block",
        "turn_block",
    )
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


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
