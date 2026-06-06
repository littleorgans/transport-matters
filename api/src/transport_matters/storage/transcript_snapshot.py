"""Tier-1 transcript snapshot writer (§7.1/§11, slice 8b-i): own the transcript at capture.

Tier-1 holds only the wire; the transcript lives only in the CLI's own file
(``~/.claude/projects/...``, ``~/.codex/sessions/...``), which the CLI or the user can GC. When
that file is gone, transcript replay loses the entire transcript half. This module is the
storage-layer half of the fix: a synchronous, append-only writer that tees a **byte-faithful**
copy of every consumed transcript record into ``<run_dir>/transcripts/<session_id>.jsonl`` as the
§9.2 tailer reads them, so a future rebuild replays TM's OWNED bytes regardless of CLI retention.

DAG: the tailer must not import a storage write API, so the writer is built here and injected
as a plain callable at ``load_runtime()``. The tailer holds an opaque
``Callable[[str, int, bytes], None]`` and never imports this module.

Idempotence (the load-bearing property): the snapshot is a byte-faithful copy of the CLI file's
consumed prefix, so its on-disk size **is** the length of the prefix already owned. A re-tail (a
fresh process re-reads the CLI file from offset 0) re-tees a range we already hold; we append only
the bytes beyond the current snapshot size, so a restart never duplicates content.

A gap (``start_offset`` ahead of the snapshot size — the snapshot file was truncated or its dir
removed mid-run) is a HARD failure, NOT a silent skip: we lack the missing bytes here, so writing
would punch a non-prefix hole AND silently let the tailer advance past un-snapshotted data. Raising
keeps the snapshot a valid prefix and stops the tailer's ``byte_offset`` from advancing past it
(the tailer's ``poll()`` catches it and retries), so session events never get ahead of tier-1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters.storage.disk_layout import DiskStorageLayout

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class TranscriptSnapshotGapError(RuntimeError):
    """The snapshot is missing bytes before *start_offset* — appending would corrupt the prefix."""


def make_transcript_snapshot_writer(storage_root: Path) -> Callable[[str, int, bytes], None]:
    """Build the injected tailer snapshot-writer, closing over the run-dir *storage_root*.

    Returns ``snapshot(session_id, start_offset, consumed)``: append the newly-consumed transcript
    bytes for *session_id*, where *consumed* mirrors the CLI byte range
    ``[start_offset, start_offset + len(consumed))`` the tailer just read. The append is synchronous
    (it runs in the tailer thread, off the §7.1 wire hot path) and idempotent on re-tail. Raises
    ``TranscriptSnapshotGapError`` if the snapshot is behind *start_offset* (see module docstring).
    """
    layout = DiskStorageLayout(storage_root)

    def snapshot(session_id: str, start_offset: int, consumed: bytes) -> None:
        if not consumed:
            return
        path = layout.transcript_snapshot_path(session_id)
        snap_size = path.stat().st_size if path.exists() else 0
        # The snapshot is a byte-faithful prefix of the CLI file, so snap_size is the prefix length
        # already owned. The incoming bytes cover CLI range [start_offset, start_offset+len).
        if start_offset > snap_size:
            raise TranscriptSnapshotGapError(
                f"transcript snapshot gap for {session_id}: "
                f"start_offset={start_offset} > snapshot_size={snap_size}"
            )
        already = (
            snap_size - start_offset
        )  # bytes at the head of *consumed* the snapshot already has
        if already >= len(consumed):
            return  # re-tail of an already-owned range → nothing new
        path.parent.mkdir(parents=True, exist_ok=True)  # recreate the dir if it was removed mid-run
        with path.open("ab") as handle:
            handle.write(consumed[already:])

    return snapshot
