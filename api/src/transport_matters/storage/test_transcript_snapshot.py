"""The tier-1 transcript snapshot writer (§7.1/§11, slice 8b-i): byte-faithful prefix-copy append.

The writer is the injected callback the §9.2 tailer tees consumed transcript bytes into. Its job:
keep ``<run_dir>/transcripts/<session_id>.jsonl`` a byte-faithful copy of the harness transcript's
consumed prefix, idempotently across re-tails (a fresh process re-reads the harness file from offset 0).
"""

from typing import TYPE_CHECKING

import pytest

from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.transcript_snapshot import (
    TranscriptSnapshotGapError,
    make_transcript_snapshot_writer,
)

if TYPE_CHECKING:
    from pathlib import Path

_SID = "019e0000-0000-7000-8000-00000000c0de"


def _snap_path(root: Path, session_id: str = _SID) -> Path:
    return DiskStorageLayout(root).transcript_snapshot_path(session_id)


def test_fresh_append_writes_consumed_bytes_verbatim(tmp_path: Path) -> None:
    snapshot = make_transcript_snapshot_writer(tmp_path)
    data = b'{"type":"session_meta"}\n{"type":"response_item"}\n'

    snapshot(_SID, 0, data)

    assert _snap_path(tmp_path).read_bytes() == data


def test_incremental_appends_preserve_order_and_bytes(tmp_path: Path) -> None:
    snapshot = make_transcript_snapshot_writer(tmp_path)
    first = b'{"a":1}\n'
    second = b'{"b":2}\n'

    snapshot(_SID, 0, first)
    snapshot(_SID, len(first), second)  # start_offset mirrors the tailer's advanced cursor

    assert _snap_path(tmp_path).read_bytes() == first + second


def test_empty_consumed_is_a_noop_and_creates_no_file(tmp_path: Path) -> None:
    snapshot = make_transcript_snapshot_writer(tmp_path)

    snapshot(_SID, 0, b"")

    assert not _snap_path(tmp_path).exists()


def test_retail_from_offset_zero_does_not_duplicate(tmp_path: Path) -> None:
    # A fresh process re-registers the cursor at byte_offset=0 and re-reads the WHOLE harness file.
    # The snapshot already holds that prefix, so re-teeing the same range must append nothing.
    snapshot = make_transcript_snapshot_writer(tmp_path)
    data = b'{"a":1}\n{"b":2}\n'
    snapshot(_SID, 0, data)

    snapshot(_SID, 0, data)  # restart: same range re-teed

    assert _snap_path(tmp_path).read_bytes() == data  # not data*2


def test_retail_from_offset_zero_appends_only_the_new_tail(tmp_path: Path) -> None:
    # Restart where the harness file grew while we were down: re-read [0, M+k) but only [M, M+k) is new.
    snapshot = make_transcript_snapshot_writer(tmp_path)
    prefix = b'{"a":1}\n'
    snapshot(_SID, 0, prefix)

    grown = prefix + b'{"b":2}\n'
    snapshot(_SID, 0, grown)  # re-read the whole, grown file

    assert _snap_path(tmp_path).read_bytes() == grown  # appended only the new tail, no dup prefix


def test_gap_ahead_of_snapshot_raises_rather_than_silently_advancing(tmp_path: Path) -> None:
    # A gap (start_offset > snapshot size) means the snapshot is missing [snap_size, start_offset).
    # Writing the new bytes would punch a non-prefix hole AND silently let the tailer advance past
    # un-snapshotted data, breaking the byte-faithful-prefix guarantee. So it is a HARD failure: the
    # tailer's poll() catches it and does NOT advance, surfacing the fault instead of losing data.
    snapshot = make_transcript_snapshot_writer(tmp_path)
    snapshot(_SID, 0, b"aa")

    with pytest.raises(TranscriptSnapshotGapError):
        snapshot(_SID, 5, b"cc")  # start_offset 5 > snapshot size 2 → gap

    assert _snap_path(tmp_path).read_bytes() == b"aa"  # still a valid prefix, no hole punched


def test_sessions_are_isolated_into_separate_files(tmp_path: Path) -> None:
    snapshot = make_transcript_snapshot_writer(tmp_path)
    other = "019e0000-0000-7000-8000-0000000000aa"

    snapshot(_SID, 0, b"one\n")
    snapshot(other, 0, b"two\n")

    assert _snap_path(tmp_path, _SID).read_bytes() == b"one\n"
    assert _snap_path(tmp_path, other).read_bytes() == b"two\n"
