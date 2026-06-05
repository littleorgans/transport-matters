"""§10.5 / §11.2 replay: rebuild tier-2 from tier-1 ALONE (the projection guarantee made real).

ONE reusable core — :func:`replay_run` — and three thin callers (:func:`backfill`,
:func:`reconcile`, :func:`rebuild`). Everything ``replay_run`` does is REUSE: it reads tier-1
through the storage models + :class:`DiskStorageLayout`, reconstructs each :class:`SessionBinding`
from the durable ``sessions.json`` (8b-ii) exactly the way the live binder does, and submits the
EXACT live ingest jobs (``build_wire_job`` / ``build_transcript_job`` via the shared
``ingest_records`` loop) through the single writer. There is no parallel ingest / parse / bind /
block-build path to drift (DRY, §11.2).

**Reads the SNAPSHOT, never the CLI file.** The transcript side replays the 8b-i tier-1 snapshot at
``transcript_snapshot_path(session_id)``; the original CLI transcript may be long gone. That is the
whole point of the arc — tier-2 survives the loss of the CLI's own file.

**DAG.** Imports ``ir`` + index siblings (ingest / tailer / sessions / maintenance / adapters /
writer / db) + storage READ surface (``IndexEntry`` / ``ExchangeArtifacts`` / ``InternalRequest`` /
``InternalResponse`` models, ``disk_layout`` path policy, ``read_run_session_facts``) + the live-run
beacon (``manifest``). It performs **no** storage WRITE: tier-1 is read-only, and every tier-2
mutation goes through the **writer** — the same single-writer path as live. ``storage`` never imports
``index``.

**Synchronous by construction.** tier-1 is read with plain file I/O over CLOSED artifacts (no growing
file, no event loop) and ``writer.submit`` is thread-safe, so replay is a sequence of cheap reads +
submits with no async surface. The async ``StorageBackend.read_index`` / ``read_exchange`` are
deliberately NOT reused here: each owns a per-instance thread pool with no ``close()`` (a backfill
over N run dirs would strand N pools) and self-heals tier-1 mid-read; replay instead reuses the same
pydantic models and path policy those methods are built on, with no caching, no rewrites, no loop.

**Idempotent.** The wire/turn upserts dedup by PK (``seq`` preserved via COALESCE) and identical
content rehashes to the same ``block.hash`` (§3.3), so a second replay adds no rows/blocks (asserted
in the tests). No ``ADAPTERS_VERSION`` / schema bump — the boot auto-replay executor is 8c-ii.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from transport_matters.index.adapters import get_adapter
from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
    decode_source_descriptor,
)
from transport_matters.index.db import index_db_path, index_rebuild_lock_path
from transport_matters.index.ingest import RunFacts, bind_exchange, build_wire_job
from transport_matters.index.maintenance import delete_run, gc_blocks, iter_run_dirs
from transport_matters.index.schema import is_rebuild_needed
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.tailer import TailCursor, ingest_records, iter_complete_records
from transport_matters.index.writer import IndexJob, IndexWriter
from transport_matters.ir import InternalRequest, InternalResponse
from transport_matters.lock import exclusive_file_lock
from transport_matters.manifest import read_all as read_live_manifests
from transport_matters.storage.base import ExchangeArtifacts, IndexEntry
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.session_facts import read_run_session_facts
from transport_matters.storage_roots import default_workspaces_root

if TYPE_CHECKING:
    import sqlite3

    from transport_matters.index.maintenance import RunDir
    from transport_matters.storage.session_facts import OwnedSessionFacts

_log = logging.getLogger(__name__)


# ── the one reusable core ──────────────────────────────────────────────────────────────


def replay_run(writer: IndexWriter, run_dir: RunDir) -> None:
    """Rebuild tier-2 for one run from tier-1 alone: wire artifacts + snapshot + ``sessions.json``.

    No live env, no ``RunContext``, no ``locate`` — the durable ``sessions.json`` IS the binding
    source and the descriptor IS the transcript source. Submits every job through *writer* (the
    single-writer path), so it is safe to call concurrently with live capture (both converge to the
    same upserted rows) and safe to re-run (idempotent upserts). Wire-then-transcript order mirrors
    the live sink so the session row's last-writer-wins columns (``minted``) land identically.
    """
    root = run_dir.root
    layout = DiskStorageLayout(root)
    facts = read_run_session_facts(root)
    entries = _read_run_index(root)
    slug, workspace_hash = _workspace_id_from_path(root)
    started = min((entry.ts for entry in entries), default=None)
    started_at = started.isoformat() if started is not None else ""
    owned = facts.sessions[0] if facts is not None and facts.sessions else None
    run_facts = _run_facts(run_dir, owned, slug, workspace_hash, started_at)

    # WIRE: read_index → per-entry read_exchange → bind_exchange → build_wire_job → submit (§11.2).
    for entry in entries:
        artifacts = _read_exchange(layout, entry)
        if artifacts is None:
            continue
        binding = bind_exchange(entry, artifacts, run_facts)
        writer.submit(build_wire_job(entry, artifacts, binding, storage_root=root))

    # TRANSCRIPT: each owned session's snapshot → iter_complete_records → ingest_records → submit.
    if facts is not None:
        for session in facts.sessions:
            _replay_transcript(writer, layout, session, slug, workspace_hash, started_at)


# ── thin callers ───────────────────────────────────────────────────────────────────────


def backfill(writer: IndexWriter, workspaces_root: Path, run_id: str | None = None) -> None:
    """Replay one run (``run_id``) or every durable run dir under *workspaces_root* (§11.2)."""
    for run_dir in iter_run_dirs(workspaces_root):
        if run_id is None or run_dir.run_id == run_id:
            replay_run(writer, run_dir)


def reconcile(writer: IndexWriter, conn: sqlite3.Connection, workspaces_root: Path) -> None:
    """Repair tier-2 against the durable on-disk run set, both directions (§10.4).

    A tier-1 dir that is **missing OR under-counted** in tier-2 → replay; a tier-2 ``run_id`` with no
    dir → delete + GC. *Under-counted* means a partially-indexed run (e.g. a §6.3 backpressure drop):
    its tier-1 ``index.jsonl`` entry count exceeds its tier-2 ``wire_exchange`` rows, so replay fills
    the gap (idempotent, §3.7 — over-replaying a fully-indexed run is a safe no-op). The **live set**
    (``manifest.read_all`` — the running-run beacon) is skipped in BOTH directions: never backfill a
    run a live writer still owns, never evict one mid-flight. *conn* only READS the current tier-2
    state; every mutation goes through *writer* (single-writer), so orphan eviction is one atomic job
    (all deletes + one GC sweep in a single per-job SAVEPOINT).
    """
    live = {m.run_id for m in read_live_manifests(workspaces_root)}
    on_disk = {run_dir.run_id: run_dir for run_dir in iter_run_dirs(workspaces_root)}
    tier2 = _tier2_run_ids(conn)
    for run_id, run_dir in on_disk.items():
        if run_id in live:
            continue
        if run_id not in tier2 or _is_undercounted(conn, run_dir):
            replay_run(writer, run_dir)
    orphans = sorted(rid for rid in tier2 if rid not in on_disk and rid not in live)
    if orphans:
        writer.submit(_evict_job(orphans))


def rebuild(workspaces_root: Path, *, db_path: Path | None = None) -> None:
    """Explicit trigger: drop tier-2 and replay every durable run dir into a fresh DB (§10.5).

    The demo + recovery entry. Boot/offline-only: it deletes ``index.db`` (+ ``-wal`` / ``-shm``),
    which on POSIX strands any writer still holding the old inode (§10.5 concurrency) — the caller
    guarantees no live writer (no boot gate / lock here; that machinery is 8c-ii). The fresh writer
    applies the schema on start; ``stop(drain=True)`` flushes, checkpoints, and closes.
    """
    path = db_path if db_path is not None else index_db_path()
    _drop_db_files(path)
    writer = IndexWriter(str(path))
    writer.start()
    try:
        backfill(writer, workspaces_root)
    finally:
        writer.stop(drain=True)


def rebuild_if_stale(
    workspaces_root: Path | None = None,
    *,
    db_path: Path | None = None,
    lock_path: Path | None = None,
) -> bool:
    """Boot-only auto-replay (§10.5, slice 8c-ii): rebuild from tier-1 iff the schema gate is stale.

    The wiring the live system calls at startup, BEFORE it opens any writer connection. When the gate
    is stale (a gated derivation bump, or a missing/uninitialized db) this rebuilds tier-2 from tier-1
    under a process-exclusive lock instead of letting the in-writer gate DROP the index to empty — the
    whole point of the slice, safe now that tier-1 is complete (8a/8b). Returns True iff a rebuild ran.

    Single-flight by ORDERING + lock, not an epoch protocol: the rebuild runs before this process opens
    any live connection, and :func:`exclusive_file_lock` serializes concurrent boots so exactly one
    rebuild touches the shared db. The staleness check is re-run UNDER the lock (double-checked) so a
    boot that blocked while a peer rebuilt sees a now-current db and skips its own destructive pass.
    ``rebuild()`` remains the only drop/replay executor; this adds no second path.
    """
    workspaces_root = workspaces_root if workspaces_root is not None else default_workspaces_root()
    db_path = db_path if db_path is not None else index_db_path()
    lock_path = lock_path if lock_path is not None else index_rebuild_lock_path()
    if not is_rebuild_needed(db_path):
        return False
    with exclusive_file_lock(lock_path):
        if not is_rebuild_needed(db_path):
            return False  # a concurrent boot rebuilt while we waited for the lock
        _log.info(
            "tier-2 schema gate is stale; rebuilding the index from tier-1 before boot (§10.5)"
        )
        rebuild(workspaces_root, db_path=db_path)
    return True


# ── tier-1 reads (sync; reuse the storage models + path policy, no backend instance) ─────


def _read_run_index(root: Path) -> list[IndexEntry]:
    """Parse the run's durable ``index.jsonl`` → ``IndexEntry`` rows (one JSON object per line).

    Dedup by id keeping the last occurrence in first-seen order — the same shape
    ``DiskStorageBackend._ensure_index_cache`` yields, so seq assignment matches live arrival order.
    A malformed durable row is skipped (not fatal), matching the live reader's tolerance.
    """
    index_path = DiskStorageLayout(root).index_path
    if not index_path.exists():
        return []
    deduped: dict[str, IndexEntry] = {}
    for raw in index_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            entry = IndexEntry.model_validate_json(line)
        except ValueError:
            _log.warning("rebuild: skipping malformed index entry in %s", index_path)
            continue
        deduped[entry.id] = entry
    return list(deduped.values())


def _read_exchange(layout: DiskStorageLayout, entry: IndexEntry) -> ExchangeArtifacts | None:
    """Load the IR parts ``build_wire_job`` needs for one exchange: request + (optional) response.

    Only ``request_ir`` / ``response_ir`` are read — the wire job's parts and correlation id come
    from those alone (``request_raw`` is unused on the rebuild path). ``None`` when the exchange dir
    or its ``request.ir.json`` is missing (an incomplete capture) → the exchange is skipped.
    """
    exchange_dir: Path | None = layout.new_exchange_dir(entry.id, now=entry.ts)
    if exchange_dir is None or not exchange_dir.is_dir():
        exchange_dir = layout.find_exchange_dir(entry.id)
    if exchange_dir is None:
        return None
    paths = layout.artifact_paths(exchange_dir)
    if not paths.request_ir.exists():
        return None
    request_ir = InternalRequest.model_validate_json(paths.request_ir.read_text(encoding="utf-8"))
    response_ir: InternalResponse | None = None
    if paths.response_ir.exists():
        response_ir = InternalResponse.model_validate_json(
            paths.response_ir.read_text(encoding="utf-8")
        )
    return ExchangeArtifacts(request_raw=b"", request_ir=request_ir, response_ir=response_ir)


# ── binding reconstruction + transcript replay ───────────────────────────────────────────


def _replay_transcript(
    writer: IndexWriter,
    layout: DiskStorageLayout,
    owned: OwnedSessionFacts,
    slug: str,
    workspace_hash: str,
    started_at: str,
) -> None:
    """Replay one owned session's transcript from its 8b-i snapshot (never the CLI file).

    Reconstructs the session_id the same way both live streams do — native if minted (claude),
    else ``synth_session_id`` (codex read-back) — so the snapshot key, the wire correlation, and the
    pivot all agree. ``decode_source_descriptor`` recovers the recorded ``source_path`` (and managed
    ``home_dir``) without the launch env. A pull-source (opencode) or an absent snapshot (wire-only
    session) is a no-op here.
    """
    adapter = get_adapter(owned.cli)
    session_id = (
        owned.native_session_id
        if owned.minted
        else synth_session_id(owned.run_id, adapter.provider, owned.native_session_id)
    )
    source = decode_source_descriptor(owned.source_descriptor)
    if not isinstance(source, FileTailSource):
        return
    snapshot = layout.transcript_snapshot_path(session_id)
    if not snapshot.exists():
        return
    records, _consumed = iter_complete_records(snapshot.read_bytes())
    binding = SessionBinding(
        session_id=session_id,
        provider=adapter.provider,
        run_id=owned.run_id,
        cwd="",
        workspace_slug=slug,
        workspace_hash=workspace_hash,
        started_at=started_at,
        cli=owned.cli,
        native_session_id=owned.native_session_id,
        minted=owned.minted,
        source_descriptor=owned.source_descriptor,
        home_dir=owned.home_dir,
    )
    cursor = TailCursor(binding=binding, source=source, adapter=adapter)
    ingest_records(records, cursor, source.path, writer.submit)


def _run_facts(
    run_dir: RunDir,
    owned: OwnedSessionFacts | None,
    slug: str,
    workspace_hash: str,
    started_at: str,
) -> RunFacts:
    """Assemble the per-run facts ``bind_exchange`` closes over, recovered from tier-1.

    ``workspace_slug`` / ``workspace_hash`` come from the run-dir path exactly; ``owned_*`` from
    ``sessions.json`` so the owned session's wire binding carries its descriptor (§5.2b). ``cwd`` is
    NOT durably recoverable from tier-1 (§11.1 → ``session.cwd`` = ``""``); it is not load-bearing —
    correlation / diff / timeline key on ``session_id`` + ``block.hash`` + ``seq``, all recovered.
    """
    return RunFacts(
        run_id=run_dir.run_id,
        cwd=None,
        workspace_slug=slug,
        workspace_hash=workspace_hash,
        started_at=started_at,
        cli=owned.cli if owned is not None else None,
        home_dir=Path(owned.home_dir) if owned is not None and owned.home_dir else None,
        owned_native_session_id=owned.native_session_id if owned is not None else None,
        owned_source_descriptor=owned.source_descriptor if owned is not None else None,
    )


# ── small helpers ────────────────────────────────────────────────────────────────────────


def _workspace_id_from_path(root: Path) -> tuple[str, str]:
    """Recover ``(workspace_slug, workspace_hash)`` from the ``{slug}/{hash}/{run_id}/`` run dir."""
    return root.parent.parent.name, root.parent.name


def _tier2_run_ids(conn: sqlite3.Connection) -> set[str]:
    """Every ``run_id`` present in tier-2 across all entity tables (the orphan-detection set)."""
    rows = conn.execute(
        "SELECT run_id FROM session WHERE run_id IS NOT NULL "
        "UNION SELECT run_id FROM wire_exchange WHERE run_id IS NOT NULL "
        "UNION SELECT run_id FROM transcript_turn WHERE run_id IS NOT NULL"
    ).fetchall()
    return {row[0] for row in rows}


def _is_undercounted(conn: sqlite3.Connection, run_dir: RunDir) -> bool:
    """Whether a run's tier-1 ``index.jsonl`` holds more exchanges than tier-2 has wire rows (§10.4).

    The under-count repair trigger: a §6.3 backpressure drop (or a partial earlier replay) leaves a
    durable run with fewer ``wire_exchange`` rows than its tier-1 index. Compares the de-duped tier-1
    entry count (the same set replay would submit) against ``COUNT(*) FROM wire_exchange`` for the run.
    """
    tier1 = len(_read_run_index(run_dir.root))
    row = conn.execute(
        "SELECT COUNT(*) FROM wire_exchange WHERE run_id = ?", (run_dir.run_id,)
    ).fetchone()
    return tier1 > int(row[0])


def _evict_job(run_ids: list[str]) -> IndexJob:
    """One writer job that deletes every orphan run then GCs in a single per-job SAVEPOINT (atomic)."""

    def apply(conn: sqlite3.Connection) -> None:
        for run_id in run_ids:
            delete_run(conn, run_id)
        gc_blocks(conn)

    return IndexJob(kind="reconcile", entity_id="reconcile", run_id="", apply=apply)


def _drop_db_files(path: Path) -> None:
    """Delete ``index.db`` and its WAL sidecars for a destructive rebuild (offline-only, §10.5)."""
    for sidecar in (path, path.with_name(f"{path.name}-wal"), path.with_name(f"{path.name}-shm")):
        sidecar.unlink(missing_ok=True)
