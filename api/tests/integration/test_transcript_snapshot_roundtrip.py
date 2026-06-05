"""Slice 8b-i real-run proof (automated): own the transcript snapshot end-to-end.

Wires the REAL ``make_transcript_snapshot_writer`` into the REAL ``TranscriptTailer`` over real temp
dirs shaped exactly like a live run: a workspace-scoped run dir (``workspaces/<slug>/<hash>/<run>/``)
holding the durable ``index.jsonl`` marker, and CLI transcript files in a separate "CLI home" the
tailer byte-tails (the live read source is unchanged — we only TEE a copy).

Proves the acceptance bullets short of launching a real CLI (that is Stuart's road-test):
  * a poll writes BOTH a tier-2 transcript job AND the tier-1 snapshot,
  * the snapshot is byte-faithful to the consumed CLI file, INCLUDING the non-conversational records
    (codex ``session_meta``) that ``normalize`` drops,
  * the snapshot lands under the run dir and ``iter_run_dirs`` finds that run dir,
  * a re-tail (fresh process re-reading the CLI file from offset 0) does not duplicate the snapshot.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from transport_matters.index.adapters.base import FileTailSource, SessionBinding
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.adapters.codex import CodexAdapter
from transport_matters.index.maintenance import iter_run_dirs
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.tailer import TailCursor, TranscriptTailer
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.transcript_snapshot import make_transcript_snapshot_writer

if TYPE_CHECKING:
    from pathlib import Path

    from transport_matters.index.writer import IndexJob

_RUN = "run1"
_CLAUDE_SID = "019e0000-0000-7000-8000-0000000c1a0d"
_CODEX_NATIVE = "019e0000-0000-7000-8000-00000000c0de"


def _run_dir(workspaces_root: Path) -> Path:
    """A run dir at the depth iter_run_dirs globs (slug/hash/run), with its durable index marker."""
    run_dir = workspaces_root / "slug" / "hash" / _RUN
    run_dir.mkdir(parents=True)
    (run_dir / "index.jsonl").write_text("")  # the durable §10.1 run marker iter_run_dirs keys on
    return run_dir


def _claude_binding() -> SessionBinding:
    return SessionBinding(
        session_id=_CLAUDE_SID,
        provider="anthropic",
        run_id=_RUN,
        cwd="/w",
        workspace_slug="slug",
        workspace_hash="hash",
        started_at="t",
        cli="claude",
        native_session_id=_CLAUDE_SID,
        minted=True,
    )


def _codex_binding() -> SessionBinding:
    return SessionBinding(
        session_id=synth_session_id(_RUN, "codex", _CODEX_NATIVE),
        provider="codex",
        run_id=_RUN,
        cwd="/w",
        workspace_slug="slug",
        workspace_hash="hash",
        started_at="t",
        cli="codex",
        native_session_id=_CODEX_NATIVE,
    )


def _claude_user_line(text: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "uuid": "u1",
            "parentUuid": None,
            "sessionId": _CLAUDE_SID,
            "isSidechain": False,
            "timestamp": "2026-06-05T12:00:00Z",
            "message": {"role": "user", "content": text},
        }
    )


def _codex_session_meta() -> str:
    return json.dumps(
        {
            "type": "session_meta",
            "payload": {"id": _CODEX_NATIVE, "timestamp": "2026-06-05T10:00:00.000Z", "cwd": "/w"},
        }
    )


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


def test_claude_and_codex_poll_writes_tier1_snapshot_byte_faithfully(tmp_path: Path) -> None:
    workspaces_root = tmp_path / "workspaces"
    run_dir = _run_dir(workspaces_root)
    layout = DiskStorageLayout(run_dir)

    # CLI transcript files live OUTSIDE the run dir (the CLI's own home), byte-tailed live.
    cli_home = tmp_path / "cli_home"
    cli_home.mkdir()
    claude_file = cli_home / "claude.jsonl"
    claude_file.write_text(_claude_user_line("hi") + "\n")
    codex_file = cli_home / "rollout.jsonl"
    codex_file.write_text(_codex_session_meta() + "\n" + _codex_response_item("hello") + "\n")

    submitted: list[IndexJob] = []
    tailer = TranscriptTailer(submitted.append, snapshot=make_transcript_snapshot_writer(run_dir))
    tailer.register(
        TailCursor(
            binding=_claude_binding(),
            source=FileTailSource(path=str(claude_file), format="claude_jsonl"),
            adapter=ClaudeAdapter(),
        )
    )
    tailer.register(
        TailCursor(
            binding=_codex_binding(),
            source=FileTailSource(path=str(codex_file), format="codex_rollout"),
            adapter=CodexAdapter(),
        )
    )

    tailer.poll()

    # BOTH tiers: tier-2 turns were submitted AND tier-1 snapshots were written.
    assert [job.kind for job in submitted] == ["transcript", "transcript"]  # claude + codex turn

    claude_snap = layout.transcript_snapshot_path(_CLAUDE_SID)
    codex_snap = layout.transcript_snapshot_path(synth_session_id(_RUN, "codex", _CODEX_NATIVE))
    # Byte-faithful to the consumed CLI file (both files end in \n → fully consumed).
    assert claude_snap.read_bytes() == claude_file.read_bytes()
    assert codex_snap.read_bytes() == codex_file.read_bytes()
    # Includes the non-conversational record normalize drops (only ONE transcript turn from codex).
    assert b"session_meta" in codex_snap.read_bytes()

    # The snapshot lands under the run dir iter_run_dirs discovers.
    discovered = list(iter_run_dirs(workspaces_root))
    assert [rd.run_id for rd in discovered] == [_RUN]
    assert codex_snap.parent.parent == discovered[0].root  # transcripts/<sid>.jsonl under run dir


def test_retail_from_fresh_process_does_not_duplicate_snapshot(tmp_path: Path) -> None:
    workspaces_root = tmp_path / "workspaces"
    run_dir = _run_dir(workspaces_root)
    layout = DiskStorageLayout(run_dir)
    codex_file = tmp_path / "rollout.jsonl"
    codex_file.write_text(_codex_session_meta() + "\n" + _codex_response_item("hello") + "\n")

    def _tail_once() -> None:
        # A fresh process: new tailer + new cursor at byte_offset=0, re-reading the WHOLE CLI file,
        # but reusing the durable snapshot file (a new writer over the same run dir).
        tailer = TranscriptTailer(
            lambda _job: None, snapshot=make_transcript_snapshot_writer(run_dir)
        )
        tailer.register(
            TailCursor(
                binding=_codex_binding(),
                source=FileTailSource(path=str(codex_file), format="codex_rollout"),
                adapter=CodexAdapter(),
            )
        )
        tailer.poll()

    _tail_once()
    snap = layout.transcript_snapshot_path(synth_session_id(_RUN, "codex", _CODEX_NATIVE))
    first = snap.read_bytes()

    _tail_once()  # restart, re-tail the same file from 0

    assert snap.read_bytes() == first  # idempotent: no duplicated records
    assert first == codex_file.read_bytes()
