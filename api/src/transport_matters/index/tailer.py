r"""The transcript file tailer (§9.2/§9.3): poll-driven, complete-record-only, crash-safe.

One tailer thread per process (sibling to the §6 writer). It owns per-session cursors, polls each
``FileTailSource`` path on a short interval, reads appended bytes, parses **complete** (newline-
terminated) records — advancing ``byte_offset`` only past the last ``\n`` so a half-written
trailing line waits for the next poll (§15 risk 6) — normalizes each, and submits a transcript
``IndexJob`` to the writer. The tailer never writes tier-2 directly; the writer emits the live
event after COMMIT (§9.4).

``iter_complete_records`` is the ONE record-iterate path, shared with §11 backfill (closed file)
— there is no second iteration to drift (DRY). DAG: imports ``index`` + ``adapters`` only.
"""

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from transport_matters.index.adapters.base import (
    FileTailSource,
    RunContext,
    TurnContext,
    decode_source_descriptor,
)
from transport_matters.index.ingest import build_transcript_job

if TYPE_CHECKING:
    from collections.abc import Callable

    from transport_matters.index.adapters.base import (
        RawRecord,
        SessionBinding,
        TranscriptAdapter,
        TranscriptSource,
    )
    from transport_matters.index.writer import IndexJob

_log = logging.getLogger(__name__)
_DEFAULT_FILE_INTERVAL_S = 0.25


def iter_complete_records(data: bytes) -> tuple[list[RawRecord], int]:
    """Parse complete (newline-terminated) JSON records from a byte buffer.

    Returns ``(records, consumed)`` where ``consumed`` is the offset just past the LAST newline;
    bytes after it (a half-written trailing line) are NOT consumed and wait for the next read
    (§9.3 / §15 risk 6 crash-safety). Malformed complete lines are skipped, not fatal. This is the
    single record-iterate seam shared by live-tail (growing file) and §11 backfill (closed file).
    """
    last_newline = data.rfind(b"\n")
    if last_newline == -1:
        return [], 0
    records: list[RawRecord] = []
    for line in data[: last_newline + 1].split(b"\n"):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError:
            _log.warning("skipping malformed transcript record")
    return records, last_newline + 1


@dataclass
class TailCursor:
    """Live position in one session's transcript source; advances as records arrive (§9.2)."""

    binding: SessionBinding
    source: TranscriptSource
    adapter: TranscriptAdapter
    byte_offset: int = 0  # FileTail: last fully-consumed byte
    seq: int = 0  # next TurnContext.seq / source_line (record ordinal within the session)
    parent_id: str | None = (
        None  # last emitted turn_id (linear-chain fallback for native-less formats)
    )
    model: str | None = None  # last model hint (e.g. codex turn_context.model), threaded onto turns
    stat_signature: tuple[int, float] | None = None  # (size, mtime) to skip unchanged files


class TranscriptTailer:
    """One poll-loop thread owning the active per-session cursors (§9.2). Polls, never inotify."""

    def __init__(
        self,
        submit: Callable[[IndexJob], None],
        *,
        interval_s: float = _DEFAULT_FILE_INTERVAL_S,
    ) -> None:
        self._submit = submit
        self._interval_s = interval_s
        self._cursors: dict[str, TailCursor] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def register(self, cursor: TailCursor) -> None:
        """Begin tailing a bound session (idempotent on session_id; thread-safe)."""
        with self._lock:
            self._cursors.setdefault(cursor.binding.session_id, cursor)

    def unregister(self, session_id: str) -> None:
        with self._lock:
            self._cursors.pop(session_id, None)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("TranscriptTailer already started")
        self._thread = threading.Thread(target=self._run, name="transcript-tailer", daemon=True)
        self._thread.start()

    def stop(self, drain: bool = True) -> None:
        """Stop the poll thread, then (if draining) a final pass to catch any last complete records.

        Call BEFORE the writer's stop so the drained turns are still accepted (close_runtime order).
        """
        if self._thread is not None:
            self._stop.set()
            self._thread.join()
            self._thread = None
        if drain:
            self.poll()

    def poll(self) -> None:
        """One pass over every cursor (the test seam too): one submitted job per normalized turn."""
        for cursor in self._snapshot():
            try:
                self._poll_cursor(cursor)
            except Exception:
                _log.exception("tailer poll failed for session %s", cursor.binding.session_id)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            self.poll()

    def _snapshot(self) -> list[TailCursor]:
        with self._lock:
            return list(self._cursors.values())

    def _poll_cursor(self, cursor: TailCursor) -> None:
        source = cursor.source
        if not isinstance(source, FileTailSource):
            return  # PullSource (opencode) polling is slice 7
        path = Path(source.path)
        # Managed-mint owns the path (pre-seeded session_meta) and claude's locate yields an existing
        # path, so the file is always present by registration; "exists but no response_item yet" is a
        # normal no-op handled below by the unchanged-stat guard. A genuinely missing path is a real
        # fault now (not a guessed glob), surfaced by poll()'s exception logging — not silently
        # swallowed by an early-return (§5.2b: the discovery-miss path is deleted).
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime)
        if cursor.stat_signature == signature:
            return  # unchanged file
        cursor.stat_signature = signature
        with path.open("rb") as handle:
            handle.seek(cursor.byte_offset)
            data = handle.read()
        records, consumed = iter_complete_records(data)
        for record in records:
            self._ingest_record(cursor, record, source.path)
        cursor.byte_offset += consumed

    def _ingest_record(self, cursor: TailCursor, record: RawRecord, source_path: str) -> None:
        # A non-turn record may carry the active model (codex turn_context); thread it forward (§5.2).
        hint = cursor.adapter.model_hint(record)
        if hint is not None:
            cursor.model = hint
        ctx = TurnContext(
            binding=cursor.binding,
            source_path=source_path,
            seq=cursor.seq,
            source_line=cursor.seq,
            parent_id=cursor.parent_id,
            model=cursor.model,
        )
        turn = cursor.adapter.normalize(record, ctx)
        cursor.seq += 1
        if turn is not None:
            self._submit(build_transcript_job(turn, cursor.binding))
            cursor.parent_id = turn.turn_id


async def register_session_cursor(
    tailer: TranscriptTailer, adapter: TranscriptAdapter, binding: SessionBinding
) -> None:
    """Re-bind via the adapter, resolve the transcript source, and register a tail cursor (§9.2).

    The wire side resolved a provisional ``binding``; re-deriving it through ``adapter.bind`` makes the
    adapter the single authority for session_id derivation (read-back synth / direct / mint) and gives
    ``bind()`` + ``RunContext`` a production caller (audit #2). For a read-back provider the adapter MUST
    reproduce the wire side's ``session_id`` (§7.2 convergence) since both synth from the same native id
    threaded via ``RunContext``; a divergence would silently empty the pivot/diff join, so it is logged
    and the wire id is kept.

    Source resolution (§5.2b managed-mint): if the binding carries a launcher-owned ``source_descriptor``
    (codex), the cursor tails that exact owned path — no discovery. Otherwise the adapter ``locate``s it
    (claude's deterministic path). A binding with neither (a codex id TM did not seed) resolves to
    ``None`` and registers no cursor: it stays pending rather than mis-joining (§15 risk 2).

    ``byte_offset = 0`` so turns written before registration (the one-frame startup lag) are caught
    on the first poll's full read.
    """
    run = RunContext(
        run_id=binding.run_id,
        cwd=binding.cwd,
        workspace_slug=binding.workspace_slug,
        workspace_hash=binding.workspace_hash,
        cli=binding.cli or adapter.cli,
        started_at=binding.started_at,
        native_session_id=binding.native_session_id,
    )
    transcript_binding = await adapter.bind(run)
    if transcript_binding.session_id != binding.session_id:
        _log.warning(
            "read-back session_id divergence (%s): wire=%s transcript=%s; keeping the wire id",
            adapter.cli,
            binding.session_id,
            transcript_binding.session_id,
        )
        transcript_binding = binding
    elif binding.source_descriptor is not None:
        # carry the launcher-owned descriptor onto the re-bound binding so the cursor tails the owned
        # path AND the transcript upsert persists the descriptor too (COALESCE-safe, §7.3).
        transcript_binding = transcript_binding.model_copy(
            update={"source_descriptor": binding.source_descriptor}
        )
    if transcript_binding.source_descriptor is not None:
        source: TranscriptSource | None = decode_source_descriptor(
            transcript_binding.source_descriptor
        )
    else:
        source = await adapter.locate(transcript_binding)
    if source is None:
        return  # no owned descriptor, no locate → stays pending (codex non-owned id, §15 risk 2)
    tailer.register(TailCursor(binding=transcript_binding, source=source, adapter=adapter))
