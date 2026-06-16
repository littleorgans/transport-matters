"""Sharded async commit dispatcher for transcript tailing."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from transport_matters.session.ingest import EventBatch
    from transport_matters.session.writer import CommitResult


class CommitQueueFull(RuntimeError):
    """Raised through a commit future when a shard queue applies backpressure."""


@dataclass(frozen=True, slots=True)
class _CommitJob:
    batch: EventBatch
    future: Future[Any]


class ShardedCommitDispatcher:
    """Bounded async commit dispatcher preserving per-session worker affinity."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        submit: Callable[[EventBatch], Awaitable[CommitResult]],
        shard_count: int,
        queue_size: int,
        commit_timeout_s: float = 5.0,
    ) -> None:
        if shard_count < 1:
            raise ValueError("shard_count must be positive")
        if queue_size < 1:
            raise ValueError("queue_size must be positive")
        self._loop = loop
        self._submit = submit
        self._shard_count = shard_count
        self._commit_timeout_s = commit_timeout_s
        self._closed = False
        self._queues: list[asyncio.Queue[_CommitJob]] = [
            asyncio.Queue(maxsize=queue_size) for _ in range(shard_count)
        ]
        self._tasks = [
            loop.create_task(
                self._worker(index, queue),
                name=f"transcript-commit-shard-{index}",
            )
            for index, queue in enumerate(self._queues)
        ]

    def submit(self, batch: EventBatch) -> Future[Any]:
        """Try to enqueue a batch without blocking the caller."""
        future: Future[Any] = Future()
        job = _CommitJob(batch=batch, future=future)
        shard = self._shard_index(batch.session.session_id)
        self._loop.call_soon_threadsafe(self._enqueue, shard, job)
        return future

    def _shard_index(self, session_id: str) -> int:
        return hash(session_id) % self._shard_count

    def _enqueue(self, shard: int, job: _CommitJob) -> None:
        if self._closed:
            job.future.set_exception(RuntimeError("commit dispatcher is closed"))
            return
        try:
            self._queues[shard].put_nowait(job)
        except asyncio.QueueFull:
            job.future.set_exception(
                CommitQueueFull(
                    f"commit shard {shard} queue is full for session {job.batch.session.session_id}"
                )
            )

    async def _worker(self, _index: int, queue: asyncio.Queue[_CommitJob]) -> None:
        while True:
            job = await queue.get()
            try:
                result = await asyncio.wait_for(
                    self._submit(job.batch),
                    timeout=self._commit_timeout_s,
                )
            except Exception as exc:
                if not job.future.done():
                    job.future.set_exception(exc)
            else:
                if not job.future.done():
                    job.future.set_result(result)
            finally:
                queue.task_done()

    async def aclose(self) -> None:
        """Drain accepted jobs, then stop worker tasks."""
        await asyncio.sleep(0)
        self._closed = True
        await asyncio.gather(*(queue.join() for queue in self._queues))
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
