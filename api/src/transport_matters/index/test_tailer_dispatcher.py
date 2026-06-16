"""Sharded tailer commit dispatch and commit-ack cursor advancement."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

from psycopg import errors

from transport_matters.index.adapters.base import FileTailSource, SessionBinding
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.commit_dispatcher import CommitQueueFull, ShardedCommitDispatcher
from transport_matters.index.conftest import make_binding
from transport_matters.index.tailer import (
    TailCursor,
    TranscriptTailer,
)
from transport_matters.index.test_tailer import _user_line
from transport_matters.session.ingest import EventBatch, build_event, build_event_batch
from transport_matters.session.quarantine import QUARANTINE_MAX_ATTEMPTS
from transport_matters.session.writer import CommitResult

if TYPE_CHECKING:
    from pathlib import Path


def _binding(session_id: str) -> SessionBinding:
    return make_binding(session_id, started_at="2026-06-05T12:00:00Z")


def _cursor(path: Path, session_id: str) -> TailCursor:
    return TailCursor(
        binding=_binding(session_id),
        source=FileTailSource(path=str(path), format="claude_jsonl"),
        adapter=ClaudeAdapter(),
    )


def _batch(session_id: str) -> EventBatch:
    return build_event_batch(_binding(session_id), [])


async def _settle_dispatch() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def _drive_until(tailer: TranscriptTailer, predicate: Any, *, attempts: int = 30) -> None:
    for _ in range(attempts):
        await _settle_dispatch()
        tailer.poll()
        if predicate():
            return
    assert predicate()


def _commit_result(batch: EventBatch) -> CommitResult:
    return CommitResult(
        ok=True,
        session_id=batch.session.session_id,
        committed=len(batch.events),
        last_seq=batch.events[-1].event.seq if batch.events else None,
    )


async def test_slow_shard_does_not_head_of_line_other_shards(tmp_path: Path) -> None:
    loop = asyncio.get_running_loop()
    poison_release = asyncio.Event()
    poison_started = asyncio.Event()
    committed: list[str] = []

    async def submit(batch: EventBatch) -> CommitResult:
        session_id = batch.session.session_id
        if session_id == poison_id:
            poison_started.set()
            await poison_release.wait()
        committed.append(session_id)
        return _commit_result(batch)

    dispatcher = ShardedCommitDispatcher(
        loop=loop,
        submit=submit,
        shard_count=10,
        queue_size=64,
    )
    poison_id = "session-poison"
    poison_shard = dispatcher._shard_index(poison_id)
    healthy_ids: list[str] = []
    candidate = 0
    while len(healthy_ids) < 49:
        session_id = f"session-healthy-{candidate}"
        if dispatcher._shard_index(session_id) != poison_shard:
            healthy_ids.append(session_id)
        candidate += 1

    try:
        tailer = TranscriptTailer(
            build_record=build_event,
            submit_batch=lambda binding, events: dispatcher.submit(
                build_event_batch(binding, events)
            ),
        )
        for index, session_id in enumerate([poison_id, *healthy_ids]):
            path = tmp_path / f"{index}.jsonl"
            path.write_text(_user_line(f"u-{index}", "hi") + "\n")
            tailer.register(_cursor(path, session_id))

        tailer.poll()
        await _drive_until(
            tailer,
            lambda: (
                poison_started.is_set()
                and len({session_id for session_id in committed if session_id in healthy_ids}) == 49
            ),
        )

        cursors = {cursor.binding.session_id: cursor for cursor in tailer._snapshot()}
        assert cursors[poison_id].byte_offset == 0
        assert all(cursors[session_id].byte_offset > 0 for session_id in healthy_ids)
    finally:
        poison_release.set()
        await dispatcher.aclose()


async def test_async_commit_failure_does_not_advance_and_retries_same_batch(
    tmp_path: Path,
) -> None:
    loop = asyncio.get_running_loop()
    attempts: list[tuple[str, tuple[int, ...]]] = []

    async def submit(batch: EventBatch) -> CommitResult:
        attempts.append(
            (batch.session.session_id, tuple(event.event.seq for event in batch.events))
        )
        if len(attempts) == 1:
            raise RuntimeError("database unavailable")
        return _commit_result(batch)

    dispatcher = ShardedCommitDispatcher(loop=loop, submit=submit, shard_count=2, queue_size=4)
    try:
        tailer = TranscriptTailer(
            build_record=build_event,
            submit_batch=lambda binding, events: dispatcher.submit(
                build_event_batch(binding, events)
            ),
        )
        path = tmp_path / "retry.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n")
        cursor = _cursor(path, "session-retry")
        tailer.register(cursor)

        tailer.poll()
        await _settle_dispatch()
        tailer.poll()

        assert attempts == [("session-retry", (0,))]
        assert cursor.byte_offset == 0
        assert cursor.seq == 0
        assert cursor.stat_signature is None

        tailer.poll()
        await _settle_dispatch()
        tailer.poll()

        assert attempts == [("session-retry", (0,)), ("session-retry", (0,))]
        assert cursor.byte_offset == len(path.read_bytes())
        assert cursor.seq == 1
    finally:
        await dispatcher.aclose()


async def test_worker_base_exception_resolves_cursor_and_restarts_for_retry(
    tmp_path: Path,
) -> None:
    class WorkerAbort(BaseException):
        pass

    loop = asyncio.get_running_loop()
    attempts: list[tuple[str, tuple[int, ...]]] = []

    async def submit(batch: EventBatch) -> CommitResult:
        attempts.append(
            (batch.session.session_id, tuple(event.event.seq for event in batch.events))
        )
        if len(attempts) == 1:
            raise WorkerAbort("worker aborted mid commit")
        return _commit_result(batch)

    dispatcher = ShardedCommitDispatcher(loop=loop, submit=submit, shard_count=1, queue_size=4)
    try:
        tailer = TranscriptTailer(
            build_record=build_event,
            submit_batch=lambda binding, events: dispatcher.submit(
                build_event_batch(binding, events)
            ),
        )
        path = tmp_path / "base-exception.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n")
        cursor = _cursor(path, "session-base-exception")
        tailer.register(cursor)

        tailer.poll()
        await _settle_dispatch()
        tailer.poll()
        tailer.poll()
        await _settle_dispatch()
        tailer.poll()

        assert attempts == [
            ("session-base-exception", (0,)),
            ("session-base-exception", (0,)),
        ]
        assert cursor.byte_offset == len(path.read_bytes())
        assert cursor.seq == 1
    finally:
        await dispatcher.aclose()


async def test_per_session_ordering_waits_for_prior_commit_ack(tmp_path: Path) -> None:
    loop = asyncio.get_running_loop()
    release_first = asyncio.Event()
    started_batches: list[tuple[str, ...]] = []
    finished_batches: list[tuple[str, ...]] = []

    async def submit(batch: EventBatch) -> CommitResult:
        native_ids = tuple(event.event.native_turn_id or "" for event in batch.events)
        started_batches.append(native_ids)
        if native_ids == ("u1",):
            await release_first.wait()
        finished_batches.append(native_ids)
        return _commit_result(batch)

    dispatcher = ShardedCommitDispatcher(loop=loop, submit=submit, shard_count=4, queue_size=8)
    try:
        tailer = TranscriptTailer(
            build_record=build_event,
            submit_batch=lambda binding, events: dispatcher.submit(
                build_event_batch(binding, events)
            ),
        )
        path = tmp_path / "ordered.jsonl"
        first = _user_line("u1", "first") + "\n"
        path.write_text(first)
        cursor = _cursor(path, "session-ordered")
        tailer.register(cursor)

        tailer.poll()
        await _settle_dispatch()
        path.write_text(first + _user_line("u2", "second") + "\n")
        tailer.poll()
        await _settle_dispatch()

        assert started_batches == [("u1",)]
        assert cursor.byte_offset == 0

        release_first.set()
        await _drive_until(tailer, lambda: finished_batches == [("u1",), ("u2",)])

        assert started_batches == [("u1",), ("u2",)]
        assert cursor.byte_offset == len(path.read_bytes())
        assert cursor.seq == 2
    finally:
        await dispatcher.aclose()


async def test_async_quarantine_ack_does_not_stall_healthy_cursor_or_advance_early(
    tmp_path: Path,
) -> None:
    poison_path = tmp_path / "poison.jsonl"
    healthy_path = tmp_path / "healthy.jsonl"
    poison_payload = _user_line("u1", "poison") + "\n"
    healthy_payload = _user_line("u2", "healthy") + "\n"
    poison_path.write_text(poison_payload)
    healthy_path.write_text(healthy_payload)
    dead_letter_ack: Future[bool] = Future()
    submitted: list[str] = []
    quarantine_calls = 0

    def submit_batch(binding: SessionBinding, _events: list[Any]) -> None:
        if binding.session_id == "session-poison":
            raise errors.UniqueViolation("unexpected constraint failure")
        submitted.append(binding.session_id)

    def quarantine_window(
        _binding: SessionBinding,
        _source_path: str,
        _byte_start: int,
        _byte_end: int,
        _raw_excerpt: bytes,
        _exc: BaseException,
        _attempts: int,
    ) -> Future[bool]:
        nonlocal quarantine_calls
        quarantine_calls += 1
        return dead_letter_ack

    tailer = TranscriptTailer(
        build_record=build_event,
        submit_batch=submit_batch,
        quarantine_window=quarantine_window,
    )
    poison_cursor = _cursor(poison_path, "session-poison")
    healthy_cursor = _cursor(healthy_path, "session-healthy")
    tailer.register(poison_cursor)

    for _ in range(QUARANTINE_MAX_ATTEMPTS - 1):
        tailer.poll()
        assert poison_cursor.byte_offset == 0

    tailer.register(healthy_cursor)
    tailer.poll()

    assert quarantine_calls == 1
    assert submitted == ["session-healthy"]
    assert poison_cursor.byte_offset == 0
    assert healthy_cursor.byte_offset == len(healthy_payload.encode())

    dead_letter_ack.set_result(True)
    tailer.poll()

    assert poison_cursor.byte_offset == len(poison_payload.encode())
    assert poison_cursor.quarantine_attempts == 0


async def test_concurrency_bound_never_exceeds_shard_count() -> None:
    loop = asyncio.get_running_loop()
    release = asyncio.Event()
    active = 0
    max_active = 0

    async def submit(batch: EventBatch) -> CommitResult:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await release.wait()
        active -= 1
        return _commit_result(batch)

    dispatcher = ShardedCommitDispatcher(loop=loop, submit=submit, shard_count=3, queue_size=32)
    try:
        futures = [dispatcher.submit(_batch(f"session-{index}")) for index in range(20)]
        await _drive_until(TranscriptTailer(), lambda: max_active == 3, attempts=20)
        assert max_active == 3
        release.set()
        for future in futures:
            await asyncio.wrap_future(future)
    finally:
        await dispatcher.aclose()


async def test_full_queue_reports_backpressure_without_commit() -> None:
    loop = asyncio.get_running_loop()
    release = asyncio.Event()

    async def submit(batch: EventBatch) -> CommitResult:
        await release.wait()
        return _commit_result(batch)

    dispatcher = ShardedCommitDispatcher(loop=loop, submit=submit, shard_count=1, queue_size=1)
    try:
        first = dispatcher.submit(_batch("session-1"))
        second = dispatcher.submit(_batch("session-2"))
        third = dispatcher.submit(_batch("session-3"))
        await _settle_dispatch()

        assert not first.done()
        assert second.done()
        assert isinstance(second.exception(), CommitQueueFull)
        assert third.done()
        assert isinstance(third.exception(), CommitQueueFull)
    finally:
        release.set()
        await dispatcher.aclose()


async def test_close_drains_enqueues_scheduled_before_close() -> None:
    loop = asyncio.get_running_loop()

    async def submit(batch: EventBatch) -> CommitResult:
        return _commit_result(batch)

    dispatcher = ShardedCommitDispatcher(loop=loop, submit=submit, shard_count=1, queue_size=1)
    future = dispatcher.submit(_batch("session-close"))

    await dispatcher.aclose()

    assert future.done()
    assert future.result().ok is True
