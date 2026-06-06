"""Transcript-only replay helpers for the Postgres session store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from transport_matters.index.adapters import get_adapter
from transport_matters.index.adapters.base import (
    FileTailSource,
    RawRecord,
    SessionBinding,
    decode_source_descriptor,
)
from transport_matters.index.maintenance import RunDir, iter_run_dirs
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.tailer import iter_complete_records
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.session_facts import OwnedSessionFacts, read_run_session_facts

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

ReplayRecord = tuple[SessionBinding, RawRecord, int, FileTailSource]


def replay_transcript_run(run_dir: RunDir | Path) -> Iterator[ReplayRecord]:
    """Yield raw transcript records from a run's durable snapshot, with no wire artifact reads."""
    root = run_dir.root if isinstance(run_dir, RunDir) else run_dir
    facts = read_run_session_facts(root)
    if facts is None:
        return
    for owned in facts.sessions:
        yield from _replay_owned(root, owned)


def replay_transcript_runs(
    workspaces_root: Path, *, run_id: str | None = None
) -> Iterator[ReplayRecord]:
    """Yield transcript records for every durable run under the workspace root."""
    for run_dir in iter_run_dirs(workspaces_root):
        if run_id is None or run_dir.run_id == run_id:
            yield from replay_transcript_run(run_dir)


def _replay_owned(root: Path, owned: OwnedSessionFacts) -> Iterator[ReplayRecord]:
    adapter = get_adapter(owned.cli)
    session_id = _session_id(owned, adapter.provider)
    source = decode_source_descriptor(owned.source_descriptor)
    if not isinstance(source, FileTailSource):
        return
    snapshot = DiskStorageLayout(root).transcript_snapshot_path(session_id)
    if not snapshot.exists():
        return
    records, _consumed = iter_complete_records(snapshot.read_bytes())
    binding = _binding(
        root,
        owned,
        adapter.provider,
        session_id,
        _started_at(records, snapshot),
        _cwd(records),
    )
    for seq, record in enumerate(records):
        yield binding, record, seq, source


def _session_id(owned: OwnedSessionFacts, provider: str) -> str:
    if owned.minted:
        return owned.native_session_id
    return synth_session_id(owned.run_id, provider, owned.native_session_id)


def _binding(
    root: Path,
    owned: OwnedSessionFacts,
    provider: str,
    session_id: str,
    started_at: str,
    cwd: str,
) -> SessionBinding:
    slug, workspace_hash = _workspace_identity(root)
    return SessionBinding(
        session_id=session_id,
        provider=provider,
        run_id=owned.run_id,
        cwd=cwd,
        workspace_slug=slug,
        workspace_hash=workspace_hash,
        started_at=started_at,
        cli=owned.cli,
        native_session_id=owned.native_session_id,
        minted=owned.minted,
        source_descriptor=owned.source_descriptor,
        home_dir=owned.home_dir,
    )


def _workspace_identity(root: Path) -> tuple[str, str]:
    return root.parent.parent.name, root.parent.name


def _started_at(records: list[RawRecord], snapshot: Path) -> str:
    for record in records:
        ts = _timestamp(record)
        if ts is not None:
            return ts
    return datetime.fromtimestamp(snapshot.stat().st_mtime, tz=UTC).isoformat()


def _cwd(records: list[RawRecord]) -> str:
    for record in records:
        value = _record_string(record, "cwd")
        if value is not None:
            return value
    return ""


def _timestamp(record: RawRecord) -> str | None:
    return _record_string(record, "timestamp")


def _record_string(record: RawRecord, key: str) -> str | None:
    value = record.get(key)
    if isinstance(value, str):
        return value
    payload = record.get("payload")
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None
