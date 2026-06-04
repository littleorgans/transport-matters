"""The single-writer-per-process actor: a bounded queue drained into batched transactions.

One dedicated OS thread owns one write ``Connection`` (sqlite3 connections are thread-affine,
so the connection is created on the thread and used nowhere else). Producers submit
non-blocking; a full queue drops + logs + marks the run dirty rather than blocking the wire
path (§6.3). Each job runs inside its own ``SAVEPOINT`` so one failure cannot pollute the
batch's other jobs.
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any  # Any: a live-event payload is a free-form JSON dict

from transport_matters.index.db import connect
from transport_matters.index.schema import apply_schema

if TYPE_CHECKING:
    import asyncio
    import sqlite3
    from collections.abc import Callable

_log = logging.getLogger(__name__)
_DEFAULT_QUEUE_MAX = 10_000


@dataclass(frozen=True)
class IndexJob:
    """One unit of tier-2 work.

    ``apply`` performs the entity's writes (session upsert → entity upsert → edge replace)
    inside the writer's per-job ``SAVEPOINT``. The concrete wire/transcript builders that
    construct these land in slices 2/4 (``index/ingest.py``); slice 1 owns the actor, the
    lifecycle, and this contract.
    """

    kind: str  # "wire" | "transcript" — metrics/logging only
    entity_id: str  # for failure logging
    run_id: str  # for dirty-marking on drop / rollback
    apply: Callable[[sqlite3.Connection], None]
    event: dict[str, Any] | None = None  # live SSE payload emitted post-COMMIT (transcript turns)


class _Stop:
    """Sentinel enqueued by ``stop()`` to wake the blocking drain loop."""


_STOP = _Stop()


class IndexWriter:
    """Single-writer-per-process actor draining a bounded queue into batched transactions."""

    def __init__(
        self,
        db_path: str,
        batch_max: int = 64,
        flush_ms: int = 50,
        queue_max: int = _DEFAULT_QUEUE_MAX,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._db_path = db_path
        self._batch_max = batch_max
        self._flush_ms = flush_ms
        self._queue: queue.Queue[IndexJob | _Stop] = queue.Queue(maxsize=queue_max)
        self._thread: threading.Thread | None = None
        self._drain_on_stop = True
        self._dropped: dict[str, int] = {}
        # Live-push (§9.4): after a successful COMMIT, emit each applied job's event on the event
        # loop via call_soon_threadsafe — the ONLY safe cross-thread bridge to the loop-affine
        # broadcast.emit (the writer is an OS thread). None loop/emit = no push (tests / tier-2-only).
        self._loop = loop
        self._emit = emit

    def start(self) -> None:
        """Spawn the writer thread (called once, from ``load_runtime()``)."""
        if self._thread is not None:
            raise RuntimeError("IndexWriter already started")
        self._thread = threading.Thread(target=self._run, name="index-writer", daemon=True)
        self._thread.start()

    def submit(self, job: IndexJob) -> None:
        """Enqueue a job without blocking; drop + log + mark the run dirty when full (§6.3)."""
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            self._mark_dropped(job)
            _log.warning(
                "index queue full; dropped %s job entity=%s run=%s (dropped_for_run=%d)",
                job.kind,
                job.entity_id,
                job.run_id,
                self._dropped[job.run_id],
            )

    def stop(self, drain: bool = True) -> None:
        """Finish the writer: flush (if ``drain``), checkpoint, and close. Idempotent."""
        if self._thread is None:
            return
        self._drain_on_stop = drain
        self._queue.put(_STOP)
        self._thread.join()
        self._thread = None

    def dropped_for(self, run_id: str) -> int:
        """Return how many jobs have been dropped/rolled back for a run (the dirty counter)."""
        return self._dropped.get(run_id, 0)

    def _run(self) -> None:
        conn = connect(self._db_path)
        apply_schema(conn)
        try:
            while self._drain_cycle(conn):
                pass
        finally:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()

    def _drain_cycle(self, conn: sqlite3.Connection) -> bool:
        """Collect and commit one batch. Return ``False`` when the writer should stop."""
        batch, stopping = self._collect_batch()
        if batch:
            self._commit_batch(conn, batch)
        if stopping and self._drain_on_stop:
            self._flush_remaining(conn)
        return not stopping

    def _collect_batch(self) -> tuple[list[IndexJob], bool]:
        first = self._queue.get()
        if isinstance(first, _Stop):
            return [], True
        batch = [first]
        deadline = time.monotonic() + self._flush_ms / 1000
        while len(batch) < self._batch_max:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                break
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                break
            if isinstance(item, _Stop):
                return batch, True
            batch.append(item)
        return batch, False

    def _flush_remaining(self, conn: sqlite3.Connection) -> None:
        while True:
            jobs = self._drain_nowait()
            if not jobs:
                return
            self._commit_batch(conn, jobs)

    def _drain_nowait(self) -> list[IndexJob]:
        jobs: list[IndexJob] = []
        while len(jobs) < self._batch_max:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if not isinstance(item, _Stop):
                jobs.append(item)
        return jobs

    def _commit_batch(self, conn: sqlite3.Connection, batch: list[IndexJob]) -> None:
        conn.execute("BEGIN IMMEDIATE")
        applied: list[IndexJob] = []
        for i, job in enumerate(batch):
            savepoint = f"j{i}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                job.apply(conn)
            except Exception:
                # Isolate the failure: ROLLBACK TO leaves the savepoint on the stack, so a
                # RELEASE must follow (a bare try/except would still commit the job's earlier
                # writes at the batch COMMIT). tier-1 is the source of truth; the §10/§11
                # rebuild recovers the rolled-back job. The wire path never observes this.
                conn.execute(f"ROLLBACK TO {savepoint}")
                conn.execute(f"RELEASE {savepoint}")
                self._mark_dropped(job)
                _log.exception("index job failed entity=%s run=%s", job.entity_id, job.run_id)
            else:
                conn.execute(f"RELEASE {savepoint}")
                applied.append(job)
        conn.execute("COMMIT")
        self._emit_events(applied)

    def _emit_events(self, applied: list[IndexJob]) -> None:
        """Push committed jobs' live events onto the event loop AFTER COMMIT (§9.4), tying the
        signal to durability: the moment the UI hears about a turn, a §8 query for it succeeds.
        ``call_soon_threadsafe`` is the only safe cross-thread bridge to the loop-affine emit."""
        loop, emit = self._loop, self._emit
        if loop is None or emit is None:
            return
        for job in applied:
            if job.event is not None:
                loop.call_soon_threadsafe(emit, job.event)

    def _mark_dropped(self, job: IndexJob) -> None:
        self._dropped[job.run_id] = self._dropped.get(job.run_id, 0) + 1
