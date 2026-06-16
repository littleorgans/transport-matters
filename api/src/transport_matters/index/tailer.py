r"""The transcript file tailer (§9.2/§9.3): poll-driven, complete-record-only, crash-safe.

One tailer thread per process. It owns per-session cursors, polls each
``FileTailSource`` path on a short interval, reads appended bytes, parses **complete** (newline-
terminated) records, advancing ``byte_offset`` only past the last ``\n`` so a half-written
trailing line waits for the next poll (§15 risk 6), normalizes each, and submits a session event
batch to the injected writer.

``iter_complete_records`` is the ONE record-iterate path and ``ingest_records`` the ONE
record→turn loop, both shared with §11 replay (closed snapshot), there is no second iteration to
drift (DRY). The writer and storage layers remain injected.
"""

import json
import logging
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, Self

from transport_matters.index.adapters.base import (
    FileTailSource,
    RunContext,
    SessionBinding,
    TurnContext,
    decode_source_descriptor,
)
from transport_matters.index.commit_dispatcher import CommitQueueFull
from transport_matters.index.subagents import (
    SubagentSpawnLink,
    discover_child_transcripts,
    is_replay_anchor,
    record_subagent_spawn_links,
)
from transport_matters.session.quarantine import QUARANTINE_MAX_ATTEMPTS, classify

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from transport_matters.index.adapters.base import (
        NormalizedTurn,
        RawRecord,
        TranscriptAdapter,
        TranscriptSource,
    )

_log = logging.getLogger(__name__)
_DEFAULT_FILE_INTERVAL_S = 0.25
_FAIL_LOG_INTERVAL_S = 30.0


class _ProvenanceWrite(Protocol):
    def model_copy(self, *, update: dict[str, object]) -> Self: ...


def _binding_extra_fields(binding: SessionBinding) -> dict[str, object]:
    """Return dynamic launch fields attached through model_copy(update=...)."""
    return {
        key: value
        for key, value in binding.__dict__.items()
        if key not in SessionBinding.model_fields
    }


@dataclass(frozen=True, slots=True)
class CompleteRecord:
    """One parsed complete record with a span relative to the current read buffer."""

    record: RawRecord
    byte_start: int
    byte_end: int
    line_index: int


@dataclass(frozen=True, slots=True)
class _CursorState:
    seq: int
    source_line: int
    parent_id: str | None
    parent_seq: int | None
    model: str | None
    skip_until_seen: bool


@dataclass(frozen=True, slots=True)
class _IngestPlan:
    writes: list[Any]
    state: _CursorState


@dataclass(frozen=True, slots=True)
class _PendingCommit:
    future: Future[Any]
    state: _CursorState
    source_path: str
    raw_excerpt: bytes
    consumed: int
    stat_signature: tuple[int, float]


@dataclass(frozen=True, slots=True)
class _PendingQuarantine:
    future: Future[Any]
    consumed: int
    stat_signature: tuple[int, float]
    attempts: int


def iter_complete_records(data: bytes) -> tuple[list[CompleteRecord], int]:
    """Parse complete (newline-terminated) JSON records from a byte buffer.

    Returns ``(records, consumed)`` where each ``CompleteRecord`` byte span is relative to this
    buffer. Callers that need absolute offsets add the cursor byte offset exactly once.
    ``consumed`` is the offset just past the LAST newline; bytes after it (a half-written trailing
    line) are NOT consumed and wait for the next read (§9.3 / §15 risk 6 crash-safety). Malformed
    complete lines are skipped, not fatal. This is the single record-iterate seam shared by live-tail
    (growing file) and §11 backfill (closed file).
    """
    last_newline = data.rfind(b"\n")
    if last_newline == -1:
        return [], 0
    records: list[CompleteRecord] = []
    complete = data[: last_newline + 1]
    byte_start = 0
    line_index = 0
    while byte_start < len(complete):
        newline = complete.find(b"\n", byte_start)
        byte_end = newline + 1
        line = complete[byte_start:newline]
        stripped = line.strip()
        if stripped:
            try:
                records.append(
                    CompleteRecord(
                        record=json.loads(stripped),
                        byte_start=byte_start,
                        byte_end=byte_end,
                        line_index=line_index,
                    )
                )
            except json.JSONDecodeError:
                _log.warning("skipping malformed transcript record")
            line_index += 1
        byte_start = byte_end
    return records, last_newline + 1


@dataclass
class TailCursor:
    """Live position in one session's transcript source; advances as records arrive (§9.2)."""

    binding: SessionBinding
    source: TranscriptSource
    adapter: TranscriptAdapter
    byte_offset: int = 0  # FileTail: last fully-consumed byte
    seq: int = 0  # next TurnContext.seq, scoped to stored rows for this session
    source_line: int = 0  # next source record ordinal, including deduped replay records
    parent_id: str | None = (
        None  # last emitted turn_id (linear-chain fallback for native-less formats)
    )
    parent_seq: int | None = None  # seq for parent_id, used by event parent_seq
    model: str | None = None  # last model hint (e.g. codex turn_context.model), threaded onto turns
    stat_signature: tuple[int, float] | None = None  # (size, mtime) to skip unchanged files
    skip_until_user_text: str | None = None
    skip_until_seen: bool = False
    quarantine_attempts: int = 0
    last_fail_log_monotonic: float | None = None
    suppressed_fail_count: int = 0
    subagent_spawn_links: dict[str, SubagentSpawnLink] = field(default_factory=dict)
    pending_codex_spawn_calls: dict[str, SubagentSpawnLink] = field(default_factory=dict)
    pending_commit: _PendingCommit | None = None
    pending_quarantine: _PendingQuarantine | None = None


def ingest_records[RecordWrite: _ProvenanceWrite](
    records: Iterable[CompleteRecord],
    cursor: TailCursor,
    source_path: str,
    *,
    build_record: Callable[[RawRecord, NormalizedTurn | None, TurnContext], RecordWrite],
    submit_batch: Callable[[SessionBinding, list[RecordWrite]], None],
) -> None:
    """Normalize records through the cursor state, then submit the built rows atomically.

    The single record→turn loop (§9.3), shared by live-tail (``_poll_cursor`` over a growing file)
    and §11 replay (over a closed snapshot): both thread ``seq`` / ``parent_id`` / ``parent_seq`` /
    ``model`` across records identically, so a rebuild reproduces the live turn ids/order exactly
    (the byte-identical replay linchpin). A non-conversational record (``normalize`` → None) still
    emits a meta event, advances ``seq``, and may set ``model`` (codex ``turn_context``), never
    ``parent_id``.
    """
    plan = _plan_ingest_records(
        records,
        cursor,
        source_path,
        build_record=build_record,
    )
    if plan.writes:
        submit_batch(cursor.binding, plan.writes)
    _apply_cursor_state(cursor, plan.state)


def _plan_ingest_records[RecordWrite: _ProvenanceWrite](
    records: Iterable[CompleteRecord],
    cursor: TailCursor,
    source_path: str,
    *,
    build_record: Callable[[RawRecord, NormalizedTurn | None, TurnContext], RecordWrite],
) -> _IngestPlan:
    """Build event writes and the cursor state to apply after durable commit ack."""
    seq = cursor.seq
    source_line = cursor.source_line
    parent_id = cursor.parent_id
    parent_seq = cursor.parent_seq
    model = cursor.model
    skip_until_seen = cursor.skip_until_seen
    writes: list[RecordWrite] = []
    from transport_matters.session.ingest import RecordProvenance

    for complete in records:
        record = complete.record
        if cursor.skip_until_user_text is not None and not skip_until_seen:
            skip_until_seen = is_replay_anchor(record, cursor.skip_until_user_text)
            if not skip_until_seen:
                source_line += 1
                continue
        hint = cursor.adapter.model_hint(record)
        if hint is not None:
            model = hint
        ctx = TurnContext(
            binding=cursor.binding,
            source_path=source_path,
            seq=seq,
            source_line=source_line,
            parent_id=parent_id,
            parent_seq=parent_seq,
            model=model,
        )
        turn = cursor.adapter.normalize(record, ctx)
        writes.append(
            build_record(record, turn, ctx).model_copy(
                update={
                    "provenance": RecordProvenance(
                        byte_start=cursor.byte_offset + complete.byte_start,
                        byte_end=cursor.byte_offset + complete.byte_end,
                    )
                }
            )
        )
        seq += 1
        source_line += 1
        if turn is not None:
            parent_id = turn.turn_id
            parent_seq = turn.seq
    return _IngestPlan(
        writes=list(writes),
        state=_CursorState(
            seq=seq,
            source_line=source_line,
            parent_id=parent_id,
            parent_seq=parent_seq,
            model=model,
            skip_until_seen=skip_until_seen,
        ),
    )


def _apply_cursor_state(cursor: TailCursor, state: _CursorState) -> None:
    cursor.seq = state.seq
    cursor.source_line = state.source_line
    cursor.parent_id = state.parent_id
    cursor.parent_seq = state.parent_seq
    cursor.model = state.model
    cursor.skip_until_seen = state.skip_until_seen


class TranscriptTailer:
    """One poll-loop thread owning the active per-session cursors (§9.2). Polls, never inotify."""

    def __init__(
        self,
        *,
        build_record: Callable[[RawRecord, NormalizedTurn | None, TurnContext], Any] | None = None,
        submit_batch: Callable[[SessionBinding, list[Any]], Future[Any] | None] | None = None,
        quarantine_window: Callable[
            [SessionBinding, str, int, int, bytes, BaseException, int], bool | Future[Any]
        ]
        | None = None,
        snapshot: Callable[[str, int, bytes], None] | None = None,
        interval_s: float = _DEFAULT_FILE_INTERVAL_S,
    ) -> None:
        self._build_record = build_record
        self._submit_batch = submit_batch
        self._quarantine_window_writer = quarantine_window
        # Injected tier-1 transcript snapshot writer (§7.1/§11, slice 8b-i): tee the consumed bytes
        # so tier-1 owns the transcript. A plain callable keeps the storage write API OUT of the
        # index-layer tailer (DAG); built + injected at load_runtime, None when no disk backend.
        # (Named ``_snapshot_writer``, ``_snapshot`` is the unrelated cursor-list snapshot below.)
        self._snapshot_writer = snapshot
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
        """One pass over every cursor, also the test seam."""
        for cursor in self._snapshot():
            try:
                self._poll_cursor(cursor)
            except Exception:
                self._log_poll_failure(cursor)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            self.poll()

    def _snapshot(self) -> list[TailCursor]:
        with self._lock:
            return list(self._cursors.values())

    def _poll_cursor(self, cursor: TailCursor) -> None:
        if not self._resolve_pending_quarantine(cursor):
            return
        if not self._resolve_pending_commit(cursor):
            return
        source = cursor.source
        if not isinstance(source, FileTailSource):
            return  # PullSource (opencode) polling is slice 7
        path = Path(source.path)
        # The cursor owns an exact source path. On managed launch the cursor can be registered before
        # the CLI creates its file, so wait on that exact path without falling back to discovery.
        try:
            stat = path.stat()
        except FileNotFoundError:
            return
        self._register_child_cursors(cursor)
        signature = (stat.st_size, stat.st_mtime)
        if cursor.stat_signature == signature:
            return  # unchanged file
        with path.open("rb") as handle:
            handle.seek(cursor.byte_offset)
            data = handle.read()
        complete, consumed = iter_complete_records(data)
        # Tee the consumed bytes into tier-1 BEFORE normalize (slice 8b-i): the raw prefix keeps ALL
        # records byte-faithfully, including the non-conversational ones normalize drops, so a
        # rebuild owns the transcript. Off the §7.1 wire hot path (tailer thread). A snapshot error
        # propagates to poll()'s try/except, leaving byte_offset AND stat_signature un-advanced (both
        # are set only after the whole poll succeeds, below), so the NEXT poll re-reads + retries even
        # if the file is unchanged, tier-1 snapshot and session events advance together or neither.
        if self._snapshot_writer is not None and consumed:
            self._snapshot_writer(cursor.binding.session_id, cursor.byte_offset, data[:consumed])
        # The ONE record→turn loop, shared verbatim with §11 replay, see ingest_records.
        if complete:
            if self._build_record is None or self._submit_batch is None:
                raise RuntimeError("TranscriptTailer requires build_record and submit_batch")
            records = [cr.record for cr in complete]
            record_subagent_spawn_links(
                provider=cursor.binding.provider,
                records=records,
                start_seq=cursor.seq,
                links=cursor.subagent_spawn_links,
                pending_codex_calls=cursor.pending_codex_spawn_calls,
            )
            try:
                plan = _plan_ingest_records(
                    complete,
                    cursor,
                    source.path,
                    build_record=self._build_record,
                )
                ack = self._submit_batch(cursor.binding, plan.writes) if plan.writes else None
            except Exception as exc:
                quarantine_ack = self._handle_commit_failure(
                    cursor, source.path, data[:consumed], consumed, exc
                )
                if isinstance(quarantine_ack, Future):
                    cursor.pending_quarantine = _PendingQuarantine(
                        future=quarantine_ack,
                        consumed=consumed,
                        stat_signature=signature,
                        attempts=cursor.quarantine_attempts,
                    )
                    return
            else:
                if isinstance(ack, Future):
                    cursor.pending_commit = _PendingCommit(
                        future=ack,
                        state=plan.state,
                        source_path=source.path,
                        raw_excerpt=data[:consumed],
                        consumed=consumed,
                        stat_signature=signature,
                    )
                    return
                _apply_cursor_state(cursor, plan.state)
                cursor.quarantine_attempts = 0
                self._register_child_cursors(cursor)
        cursor.byte_offset += consumed
        if consumed:
            cursor.quarantine_attempts = 0
            self._reset_poll_failures(cursor)
        # Mark this stat consumed LAST (mirroring byte_offset): only a fully-successful poll skips the
        # next unchanged read. A mid-poll raise leaves the old signature so the stat guard re-enters.
        cursor.stat_signature = signature

    def _resolve_pending_quarantine(self, cursor: TailCursor) -> bool:
        pending = cursor.pending_quarantine
        if pending is None:
            return True
        if not pending.future.done():
            return False
        cursor.pending_quarantine = None
        try:
            acknowledged = pending.future.result()
        except Exception:
            raise
        if not acknowledged:
            raise RuntimeError("transcript quarantine write failed")
        self._log_quarantined_window(cursor, pending.consumed, pending.attempts)
        self._mark_consumed(cursor, pending.consumed, pending.stat_signature)
        return True

    def _resolve_pending_commit(self, cursor: TailCursor) -> bool:
        pending = cursor.pending_commit
        if pending is None:
            return True
        if not pending.future.done():
            return False
        cursor.pending_commit = None
        try:
            result = pending.future.result()
        except CommitQueueFull:
            return True
        except Exception as exc:
            quarantine_ack = self._handle_commit_failure(
                cursor,
                pending.source_path,
                pending.raw_excerpt,
                pending.consumed,
                exc,
            )
            if isinstance(quarantine_ack, Future):
                cursor.pending_quarantine = _PendingQuarantine(
                    future=quarantine_ack,
                    consumed=pending.consumed,
                    stat_signature=pending.stat_signature,
                    attempts=cursor.quarantine_attempts,
                )
                return False
            if quarantine_ack:
                self._mark_consumed(cursor, pending.consumed, pending.stat_signature)
                return True
            raise
        if not result.ok:
            raise RuntimeError("session writer commit failed")
        _apply_cursor_state(cursor, pending.state)
        self._mark_consumed(cursor, pending.consumed, pending.stat_signature)
        self._register_child_cursors(cursor)
        return True

    def _handle_commit_failure(
        self,
        cursor: TailCursor,
        source_path: str,
        raw_excerpt: bytes,
        consumed: int,
        exc: BaseException,
    ) -> bool | Future[Any]:
        if classify(exc) == "transient":
            cursor.quarantine_attempts = 0
            raise exc
        cursor.quarantine_attempts += 1
        if cursor.quarantine_attempts < QUARANTINE_MAX_ATTEMPTS:
            raise exc
        quarantine_ack = self._quarantine_window(cursor, source_path, raw_excerpt, consumed, exc)
        if isinstance(quarantine_ack, Future):
            return quarantine_ack
        if not quarantine_ack:
            raise exc
        self._log_quarantined_window(cursor, consumed, cursor.quarantine_attempts)
        cursor.quarantine_attempts = 0
        return True

    def _log_quarantined_window(self, cursor: TailCursor, consumed: int, attempts: int) -> None:
        _log.warning(
            "quarantined transcript window run=%s session=%s span=%d..%d attempts=%d",
            cursor.binding.run_id,
            cursor.binding.session_id,
            cursor.byte_offset,
            cursor.byte_offset + consumed,
            attempts,
        )

    def _mark_consumed(
        self,
        cursor: TailCursor,
        consumed: int,
        signature: tuple[int, float],
    ) -> None:
        cursor.byte_offset += consumed
        if consumed:
            cursor.quarantine_attempts = 0
            self._reset_poll_failures(cursor)
        cursor.stat_signature = signature

    def _quarantine_window(
        self,
        cursor: TailCursor,
        source_path: str,
        data: bytes,
        consumed: int,
        exc: BaseException,
    ) -> bool | Future[Any]:
        if self._quarantine_window_writer is None:
            return False
        return self._quarantine_window_writer(
            cursor.binding,
            source_path,
            cursor.byte_offset,
            cursor.byte_offset + consumed,
            data[:consumed],
            exc,
            cursor.quarantine_attempts,
        )

    def _log_poll_failure(self, cursor: TailCursor) -> None:
        now = time.monotonic()
        if (
            cursor.last_fail_log_monotonic is not None
            and now - cursor.last_fail_log_monotonic < _FAIL_LOG_INTERVAL_S
        ):
            cursor.suppressed_fail_count += 1
            return
        self._log_suppressed_failures(cursor)
        _log.exception("tailer poll failed for session %s", cursor.binding.session_id)
        cursor.last_fail_log_monotonic = now

    def _reset_poll_failures(self, cursor: TailCursor) -> None:
        self._log_suppressed_failures(cursor)
        cursor.last_fail_log_monotonic = None

    def _log_suppressed_failures(self, cursor: TailCursor) -> None:
        if cursor.suppressed_fail_count == 0:
            return
        _log.warning(
            "suppressed %d repeated tailer poll failure(s) for session %s",
            cursor.suppressed_fail_count,
            cursor.binding.session_id,
        )
        cursor.suppressed_fail_count = 0

    def _register_child_cursors(self, cursor: TailCursor) -> None:
        source = cursor.source
        if not isinstance(source, FileTailSource):
            return
        for child in discover_child_transcripts(
            parent_binding=cursor.binding,
            parent_source=source,
            spawn_links=cursor.subagent_spawn_links,
        ):
            self.register(
                TailCursor(
                    binding=child.binding,
                    source=child.source,
                    adapter=cursor.adapter,
                    skip_until_user_text=child.skip_until_user_text,
                )
            )


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

    Source resolution (§5.2b/§5.2c managed-mint): if the binding carries a launcher-owned
    ``source_descriptor`` (claude or codex managed), the cursor tails that exact owned path, no
    discovery. Otherwise the adapter ``locate``s it (claude's deterministic ``~/.claude`` path, the
    external-adoption fallback). A binding with neither (a codex id TM did not seed) resolves to
    ``None`` and registers no cursor: it stays pending rather than mis-joining (§15 risk 2).

    The re-bind re-derives only session_id + native id, so the wire side's authoritative ``minted``
    (§5.2c) and owned descriptor are carried back onto the transcript binding, otherwise the
    transcript path's session upsert (``minted = excluded.minted``, last-writer-wins) would clobber a
    managed claude session's ``minted=1`` to 0 once a turn lands.

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
        home_dir=binding.home_dir,  # carried like cwd so adapter.bind/locate resolves under managed home
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
    else:
        # Carry the wire side's authoritative minted (§5.2c) + launcher-owned descriptor (§5.2b) onto
        # the re-bound binding: the cursor tails the owned path, the transcript upsert persists the
        # descriptor, and minted survives the re-bind (which always reports False for direct-id
        # adapters). COALESCE-style on the descriptor: keep the re-bound one only when the wire side
        # had none, so an external-adoption claude binding still falls through to ``locate``.
        transcript_binding = transcript_binding.model_copy(
            update={
                **_binding_extra_fields(binding),
                "minted": binding.minted,
                "source_descriptor": binding.source_descriptor
                or transcript_binding.source_descriptor,
                "template_provenance": binding.template_provenance,
                "parent_session_id": binding.parent_session_id,
                "forked_at_seq": binding.forked_at_seq,
            }
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
