"""IndexWriter actor: idempotent submit, drain + checkpoint, backpressure drop, failure isolation."""

from typing import TYPE_CHECKING

from transport_matters.index.blocks import upsert_block
from transport_matters.index.db import connect
from transport_matters.index.writer import IndexJob, IndexWriter
from transport_matters.ir import TextBlock

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from transport_matters.index.blocks import IndexablePart


def _block_job(run_id: str, part: IndexablePart) -> IndexJob:
    def apply(conn: sqlite3.Connection) -> None:
        upsert_block(conn, part)

    return IndexJob(kind="wire", entity_id="e", run_id=run_id, apply=apply)


def _failing_job(run_id: str) -> IndexJob:
    def apply(conn: sqlite3.Connection) -> None:
        raise RuntimeError("boom")

    return IndexJob(kind="wire", entity_id="bad", run_id=run_id, apply=apply)


def _block_count(db_path: str) -> int:
    verify = connect(db_path)
    try:
        return int(verify.execute("SELECT COUNT(*) FROM block").fetchone()[0])
    finally:
        verify.close()


class TestIndexWriter:
    def test_idempotent_submit_keeps_one_row(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "index.db")
        writer = IndexWriter(db_path, flush_ms=5)
        writer.start()
        writer.submit(_block_job("run1", TextBlock(text="dup")))
        writer.submit(_block_job("run1", TextBlock(text="dup")))
        writer.stop(drain=True)
        assert _block_count(db_path) == 1

    def test_drain_commits_all_pending_and_is_visible_after_stop(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "index.db")
        writer = IndexWriter(db_path, flush_ms=5)
        writer.start()
        for i in range(5):
            writer.submit(_block_job("run1", TextBlock(text=f"t{i}")))
        writer.stop(drain=True)
        assert _block_count(db_path) == 5

    def test_queue_full_drops_and_marks_run_dirty(self) -> None:
        # Not started, so nothing drains: the second submit overflows the size-1 queue.
        writer = IndexWriter("unused.db", queue_max=1)
        writer.submit(_block_job("run1", TextBlock(text="a")))
        writer.submit(_block_job("run1", TextBlock(text="b")))
        assert writer.dropped_for("run1") == 1

    def test_failed_job_is_isolated_and_survivor_commits(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "index.db")
        writer = IndexWriter(db_path, flush_ms=5)
        writer.start()
        writer.submit(_failing_job("run1"))
        writer.submit(_block_job("run1", TextBlock(text="survivor")))
        writer.stop(drain=True)
        assert _block_count(db_path) == 1
        assert writer.dropped_for("run1") >= 1

    def test_stop_is_idempotent(self, tmp_path: Path) -> None:
        writer = IndexWriter(str(tmp_path / "index.db"), flush_ms=5)
        writer.start()
        writer.stop(drain=True)
        writer.stop(drain=True)  # second stop is a no-op
