"""§10 tier-2 maintenance: the durable run enumerator + tier-2 delete + block GC.

This is the launch-state-free half of §10. Backfill / rebuild / reconcile are NOT here — they
carry the connection-quiescence and ``sessions.json`` rebuild-faithfulness decisions and land
in a later slice; nothing here depends on launch state (``owned_*`` / ``source_descriptor`` /
the launch env).

**Single-writer (load-bearing).** Tier-2 has exactly one writer per process — the §6
``IndexWriter`` thread, serialized across processes by WAL + ``busy_timeout`` (the ``db.py``
PRAGMAs). The mutators here (``delete_run``, ``delete_exchange``, ``gc_blocks``) take that
writer's ``Connection`` and run their SQL *inside the caller's transaction*; they never open a
second write connection (which would defeat the file-level single-writer discipline). They are
the body of a maintenance job: submitting
``IndexJob(kind="maintenance", entity_id=run_id, run_id=run_id, apply=lambda c: delete_run(c, run_id))``
runs them on the writer thread inside its ``BEGIN IMMEDIATE`` + per-job ``SAVEPOINT``
(``writer.py`` ``_commit_batch``); an offline caller wraps them in ``db.transaction``
(``db.py`` ``transaction``). They hold no ``BEGIN`` / ``COMMIT`` of their own, so they compose
with either boundary.

Atomicity is per-transaction, NOT per-batch: ``delete_*`` and ``gc_blocks`` are atomic together
only when ONE ``apply`` calls both (a single savepoint), or an offline ``db.transaction`` wraps
both. Submitting them as two SEPARATE jobs is not atomic — ``_commit_batch`` isolates each job in
its own ``SAVEPOINT`` and commits the survivors, so a failing GC would not roll back an
already-applied delete (tier-1 still repairs it via the §10.4 reconcile / §10.5 rebuild). So when
the §10.3 GC timing (after a delete batch, on an idle timer, at ``stop(drain=True)``) needs the
delete + GC to be all-or-nothing, enqueue them as one combined ``apply``.

**Tier-1 contract (§10.2).** Delete here is **tier-2-only**. Tier-1 is the source of truth and
the rebuildable substrate for the §10.4 reconcile / §10.5 rebuild, so maintenance never unlinks
a tier-1 run dir. Tier-1 deletion is the storage layer's job (``storage/disk.py`` staged-delete,
the async ``delete_exchange``), driven by the existing ``exchange_deleted`` broadcast — the two
tiers are parallel mirrors of one delete event, not one calling the other. Keeping tier-1 intact
is exactly what lets a mistaken tier-2 delete be repaired by replay.

``iter_run_dirs`` is a pure, durable filesystem read (glob only) — no DB, no manifest, no
live-set filtering (filtering against the live ``manifest.read_all`` set is reconcile's job).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

# The durable per-run marker is the wire index ``index.jsonl`` — written for the life of the run
# dir (``storage/disk.py``), unlike the manifest, which is a liveness beacon unlinked on exit
# (``launch_runtime.py`` ``manifest_path.unlink()``). Same ``{slug}/{hash}/{run_id}/`` depth as
# ``manifest.read_all`` (``manifest.py`` ``root.glob("*/*/*/manifest.json")``), keyed on the
# durable artifact instead of the beacon (§10.1).
_INDEX_GLOB = "*/*/*/index.jsonl"


@dataclass(frozen=True)
class RunDir:
    """A durable run directory discovered by ``iter_run_dirs``: its root + the run id."""

    root: Path
    run_id: str


def iter_run_dirs(workspaces_root: Path) -> Iterator[RunDir]:
    """Yield every run dir holding a durable ``index.jsonl`` under *workspaces_root* (§10.1).

    The durable substitute for ``manifest.read_all`` that every §10/§11 maintenance caller uses
    for run discovery: a completed run has unlinked its manifest but kept its ``index.jsonl``, so
    enumerating manifests would miss all history (the §10.1 peer-blocked-beacon bug). ``run_id``
    is the run-dir name (``resolve_storage_dir``, ``launch_runtime.py``). ``Path.glob`` on a
    missing root yields nothing, so an absent ``workspaces_root`` is an empty enumeration.
    """
    for index_path in workspaces_root.glob(_INDEX_GLOB):
        yield RunDir(root=index_path.parent, run_id=index_path.parent.name)


def delete_run(conn: sqlite3.Connection, run_id: str) -> None:
    """Delete all tier-2 rows for *run_id* (§10.2).

    Entities first so their block edges cascade (``schema.py`` ON DELETE CASCADE on
    ``exchange_block`` / ``turn_block``), then the session rows (whose entities are already
    gone). ``block`` rows are never touched here — blocks are global and shared across runs;
    orphans are reclaimed by ``gc_blocks``, which the caller enqueues afterward. Tier-2-only
    (see module docstring): tier-1 run dirs are not unlinked. Runs on the writer connection
    inside the caller's transaction.
    """
    conn.execute("DELETE FROM wire_exchange   WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM transcript_turn WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM session         WHERE run_id = ?", (run_id,))


def delete_exchange(conn: sqlite3.Connection, exchange_id: str) -> None:
    """Delete one wire exchange and its ``exchange_block`` edges (§10.2).

    The tier-2 mirror of the wire-side ``exchange_deleted`` broadcast; edges cascade, the block
    rows survive (reclaimed by ``gc_blocks``). Runs on the writer connection inside the caller's
    transaction.
    """
    conn.execute("DELETE FROM wire_exchange WHERE exchange_id = ?", (exchange_id,))


def gc_blocks(conn: sqlite3.Connection) -> int:
    """Mark-sweep every ``block`` referenced by no edge; return how many were reclaimed (§10.3).

    The predicate checks BOTH edge tables, so a block shared across the wire and transcript
    streams (the §3.3 dedup linchpin) survives until both its ``exchange_block`` and
    ``turn_block`` refs are gone. ``NOT EXISTS`` (not ``NOT IN``) lets the planner ride the
    ``exchange_block_block`` / ``turn_block_block`` indexes and short-circuit — ``block`` is the
    largest table. Deleting a block fires the ``block_ad`` trigger (``schema.py``), evicting its
    ``block_fts`` row so FTS never holds orphans. Idempotent: a re-run over a clean store
    reclaims nothing (returns 0). Runs on the writer connection inside the caller's transaction.
    """
    cur = conn.execute(
        """
        DELETE FROM block
        WHERE NOT EXISTS (SELECT 1 FROM exchange_block WHERE exchange_block.block_id = block.id)
          AND NOT EXISTS (SELECT 1 FROM turn_block     WHERE turn_block.block_id     = block.id)
        """
    )
    return cur.rowcount
