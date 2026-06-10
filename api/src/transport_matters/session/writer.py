"""Async Postgres writer for transcript session events."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from transport_matters.session.async_dao import AsyncSessionDao

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool

    from transport_matters.session.ingest import EventBatch


class CommitResult(BaseModel):
    """Result returned after the Postgres transaction has committed."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    session_id: str
    committed: int
    last_seq: int | None = None


class SessionWriter:
    """Thread-safe blocking facade over an async Postgres commit coroutine."""

    def __init__(
        self,
        pool: AsyncConnectionPool[AsyncConnection[DictRow]],
        *,
        loop: asyncio.AbstractEventLoop,
        commit_timeout_s: float = 5.0,
        notify_channel: str = "tm_events",
    ) -> None:
        self._pool = pool
        self._loop = loop
        self._commit_timeout_s = commit_timeout_s
        self._notify_channel = notify_channel
        self._open_lock = asyncio.Lock()

    def submit_blocking(self, batch: EventBatch) -> CommitResult:
        """Block the caller until the event batch is durably committed."""
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self._loop:
            raise RuntimeError("submit_blocking cannot run on the target event loop")
        future = asyncio.run_coroutine_threadsafe(self._commit_batch(batch), self._loop)
        try:
            return future.result(timeout=self._commit_timeout_s)
        except FutureTimeoutError:
            future.cancel()
            raise

    async def aclose(self) -> None:
        """Close the underlying async pool if it was opened."""
        if not self._pool.closed:
            await self._pool.close()

    async def _commit_batch(self, batch: EventBatch) -> CommitResult:
        await self._ensure_open()
        async with self._pool.connection() as conn, conn.transaction():
            dao = AsyncSessionDao(conn)
            await dao.upsert_session(batch.session)
            for item in batch.events:
                await dao.insert_event(item.event)
                for artifact in item.artifacts:
                    row = await dao.upsert_artifact(artifact.data, media_type=artifact.media_type)
                    await dao.link_artifact(
                        item.event.session_id,
                        item.event.seq,
                        row.hash,
                        artifact.ref,
                    )
            await conn.execute(
                "SELECT pg_notify(%s, %s)",
                (self._notify_channel, _notify_payload(batch)),
            )
        return CommitResult(
            ok=True,
            session_id=batch.session.session_id,
            committed=len(batch.events),
            last_seq=batch.events[-1].event.seq if batch.events else None,
        )

    async def _ensure_open(self) -> None:
        if not self._pool.closed:
            return
        async with self._open_lock:
            if self._pool.closed:
                await self._pool.open()


def _notify_payload(batch: EventBatch) -> str:
    seqs = [item.event.seq for item in batch.events]
    payload = {
        "type": "session_events",
        "session_id": batch.session.session_id,
        "run_id": batch.session.run_id,
        "count": len(batch.events),
        "first_seq": seqs[0] if seqs else None,
        "last_seq": seqs[-1] if seqs else None,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
