"""Async Postgres writer for transcript session events."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TYPE_CHECKING

import psycopg
from pydantic import BaseModel, ConfigDict

from transport_matters.session.async_dao import AsyncSessionDao
from transport_matters.session.models import DeadLetterWrite
from transport_matters.session.quarantine import classify

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool

    from transport_matters.index.adapters.base import SessionBinding
    from transport_matters.session.ingest import EventBatch, EventWrite


class CommitResult(BaseModel):
    """Result returned after the Postgres transaction has committed."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    session_id: str
    committed: int
    quarantined: int = 0
    quarantine_sqlstates: tuple[str | None, ...] = ()
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
        self._raise_if_target_loop("submit_blocking")
        future = asyncio.run_coroutine_threadsafe(self.submit(batch), self._loop)
        try:
            return future.result(timeout=self._commit_timeout_s)
        except FutureTimeoutError:
            future.cancel()
            raise

    async def submit(self, batch: EventBatch) -> CommitResult:
        """Commit an event batch from a worker running on the writer loop."""
        running_loop = asyncio.get_running_loop()
        if running_loop is not self._loop:
            raise RuntimeError("submit must run on the target event loop")
        return await self._commit_batch(batch)

    def quarantine_window_blocking(
        self,
        binding: SessionBinding,
        source_path: str,
        byte_start: int,
        byte_end: int,
        raw_excerpt: bytes,
        exc: BaseException,
        attempts: int,
    ) -> bool:
        """Block until a whole transcript window is durably dead-lettered."""
        self._raise_if_target_loop("quarantine_window_blocking")
        future = asyncio.run_coroutine_threadsafe(
            self.quarantine_window(
                binding,
                source_path,
                byte_start,
                byte_end,
                raw_excerpt,
                exc,
                attempts,
            ),
            self._loop,
        )
        try:
            return future.result(timeout=self._commit_timeout_s)
        except FutureTimeoutError:
            future.cancel()
            raise

    async def quarantine_window(
        self,
        binding: SessionBinding,
        source_path: str,
        byte_start: int,
        byte_end: int,
        raw_excerpt: bytes,
        exc: BaseException,
        attempts: int,
    ) -> bool:
        """Durably dead-letter a whole transcript window from the writer loop."""
        running_loop = asyncio.get_running_loop()
        if running_loop is not self._loop:
            raise RuntimeError("quarantine_window must run on the target event loop")
        await self._insert_dead_letter(
            _dead_letter_from_window(
                binding,
                source_path,
                byte_start,
                byte_end,
                raw_excerpt,
                exc,
                attempts,
            )
        )
        return True

    async def aclose(self) -> None:
        """Close the underlying async pool if it was opened."""
        if not self._pool.closed:
            await self._pool.close()

    async def _commit_batch(self, batch: EventBatch) -> CommitResult:
        await self._ensure_open()
        rejected: list[tuple[EventWrite, psycopg.Error]] = []
        async with self._pool.connection() as conn, conn.transaction():
            dao = AsyncSessionDao(conn)
            try:
                async with conn.transaction():
                    await dao.upsert_session(batch.session)
            except psycopg.Error as exc:
                if classify(exc) == "poison":
                    for item in batch.events:
                        await dao.insert_dead_letter(
                            _dead_letter_from_event(item, exc, batch.session.native_session_id)
                        )
                    return CommitResult(
                        ok=True,
                        session_id=batch.session.session_id,
                        committed=0,
                        quarantined=len(batch.events),
                        quarantine_sqlstates=tuple(exc.sqlstate for _item in batch.events),
                    )
                raise
            for item in batch.events:
                try:
                    async with conn.transaction():
                        await dao.insert_event(item.event)
                        for artifact in item.artifacts:
                            row = await dao.upsert_artifact(
                                artifact.data, media_type=artifact.media_type
                            )
                            await dao.link_artifact(
                                item.event.session_id,
                                item.event.seq,
                                row.hash,
                                artifact.ref,
                            )
                except psycopg.Error as exc:
                    if classify(exc) == "poison":
                        rejected.append((item, exc))
                        continue
                    raise
            for item, error in rejected:
                await dao.insert_dead_letter(
                    _dead_letter_from_event(item, error, batch.session.native_session_id)
                )
            await conn.execute(
                "SELECT pg_notify(%s, %s)",
                (self._notify_channel, _notify_payload(batch)),
            )
        return CommitResult(
            ok=True,
            session_id=batch.session.session_id,
            committed=len(batch.events) - len(rejected),
            quarantined=len(rejected),
            quarantine_sqlstates=tuple(error.sqlstate for _item, error in rejected),
            last_seq=batch.events[-1].event.seq if batch.events else None,
        )

    async def _insert_dead_letter(self, letter: DeadLetterWrite) -> None:
        await self._ensure_open()
        async with self._pool.connection() as conn, conn.transaction():
            await AsyncSessionDao(conn).insert_dead_letter(letter)

    def _raise_if_target_loop(self, method: str) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if running_loop is self._loop:
            raise RuntimeError(f"{method} cannot run on the target event loop")

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


def _dead_letter_from_event(
    item: EventWrite, exc: psycopg.Error, native_session_id: str | None
) -> DeadLetterWrite:
    provenance = item.provenance
    if provenance is None:
        raise RuntimeError("cannot quarantine event without byte provenance")
    return DeadLetterWrite(
        session_id=item.event.session_id,
        seq=item.event.seq,
        scope="record",
        run_id=item.event.run_id,
        native_session_id=native_session_id,
        provider=item.event.provider,
        cli=item.event.cli,
        source_path=item.event.source_path,
        source_line=item.event.source_line,
        event_kind=str(item.event.kind),
        byte_start=provenance.byte_start,
        byte_end=provenance.byte_end,
        error_sqlstate=exc.sqlstate,
        error_class=exc.__class__.__name__,
        error_message=str(exc),
        raw_excerpt=_raw_excerpt(item),
    )


def _dead_letter_from_window(
    binding: SessionBinding,
    source_path: str,
    byte_start: int,
    byte_end: int,
    raw_excerpt: bytes,
    exc: BaseException,
    attempts: int,
) -> DeadLetterWrite:
    return DeadLetterWrite(
        session_id=binding.session_id,
        scope="window",
        run_id=binding.run_id,
        native_session_id=binding.native_session_id,
        provider=binding.provider,
        cli=binding.cli,
        source_path=source_path,
        byte_start=byte_start,
        byte_end=byte_end,
        error_sqlstate=_sqlstate(exc),
        error_class=exc.__class__.__name__,
        error_message=str(exc),
        raw_excerpt=raw_excerpt,
        attempts=attempts,
    )


def _raw_excerpt(item: EventWrite) -> bytes:
    return json.dumps(
        item.event.raw, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _sqlstate(exc: BaseException) -> str | None:
    return exc.sqlstate if isinstance(exc, psycopg.Error) else None
