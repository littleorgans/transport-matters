"""FastAPI read surface for the Postgres session store."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from transport_matters.session.dao import AsyncSessionDao
from transport_matters.session.listen import SessionEventHub, SessionEventSignal

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from psycopg import AsyncConnection
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool

    from transport_matters.session.models import EventRow, SessionRow

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_OWNER = "local"
STREAM_KEEPALIVE_S = 15.0
STREAM_FETCH_LIMIT = 1000


class SessionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    provider: str
    cli: str | None
    run_id: str
    cwd: str
    workspace_slug: str
    workspace_hash: str
    native_session_id: str | None
    minted: bool
    source_descriptor: dict[str, Any] | None
    home_dir: str | None
    owner: str
    status: str
    title: str | None
    parent_session_id: str | None
    forked_at_seq: int | None
    started_at: datetime
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_row(cls, row: SessionRow) -> SessionSummary:
        return cls.model_validate(row.model_dump())


class SessionEventView(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    seq: int
    kind: str
    native_turn_id: str | None
    parent_native_id: str | None
    parent_seq: int | None
    run_id: str
    provider: str
    cli: str
    role: str | None
    is_sidechain: bool
    ts: datetime | None
    model: str | None
    ir: dict[str, Any] | None
    source_path: str | None
    source_line: int | None
    search_text: str | None
    created_at: datetime | None

    @classmethod
    def from_row(cls, row: EventRow) -> SessionEventView:
        data = row.model_dump(exclude={"raw"})
        return cls.model_validate(data)


class SessionEventListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: list[SessionEventView]
    next_from_seq: int | None = None


async def _session_pool(request: Request) -> AsyncConnectionPool[AsyncConnection[DictRow]]:
    pool = getattr(request.app.state, "session_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="session store unavailable")
    return cast("AsyncConnectionPool[AsyncConnection[DictRow]]", pool)


def _session_hub(request: Request) -> SessionEventHub:
    hub = getattr(request.app.state, "session_event_hub", None)
    if not isinstance(hub, SessionEventHub):
        raise HTTPException(status_code=503, detail="session event stream unavailable")
    return hub


@router.get("/sessions")
async def list_sessions(
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    workspace_hash: Annotated[str | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    cli: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(pattern="^(active|completed|archived)$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SessionSummary]:
    async with pool.connection() as conn:
        dao = AsyncSessionDao(conn)
        rows = await dao.list_sessions(
            owner=owner,
            workspace_hash=workspace_hash,
            provider=provider,
            cli=cli,
            status=status,
            limit=limit,
            offset=offset,
        )
    return [SessionSummary.from_row(row) for row in rows]


@router.get("/sessions/{session_id}/events")
async def list_session_events(
    session_id: str,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    from_seq: Annotated[int | None, Query(ge=0)] = None,
    to_seq: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> SessionEventListResponse:
    async with pool.connection() as conn:
        await _require_session(conn, session_id, owner)
        rows = await AsyncSessionDao(conn).get_events_for_owner(
            session_id,
            owner=owner,
            from_seq=from_seq,
            to_seq=to_seq,
            limit=limit,
        )
    events = [SessionEventView.from_row(row) for row in rows]
    next_from_seq = events[-1].seq + 1 if len(events) == limit else None
    return SessionEventListResponse(events=events, next_from_seq=next_from_seq)


@router.get("/sessions/{session_id}/events/stream")
async def stream_session_events(
    session_id: str,
    pool: Any = Depends(_session_pool),
    hub: SessionEventHub = Depends(_session_hub),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    last_seq: Annotated[int, Query(ge=-1)] = -1,
) -> StreamingResponse:
    async with pool.connection() as conn:
        await _require_session(conn, session_id, owner)
    generator = _event_stream(session_id, owner, last_seq, pool, hub)
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _event_stream(
    session_id: str,
    owner: str,
    last_seq: int,
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    hub: SessionEventHub,
) -> AsyncGenerator[str]:
    subscription = hub.subscribe(session_id)
    sent_seq = last_seq
    try:
        async for view in _load_event_views(pool, session_id, owner, sent_seq + 1, None):
            if view.seq > sent_seq:
                sent_seq = view.seq
                yield _sse_data(view)
        while True:
            try:
                signal = await asyncio.wait_for(
                    subscription.queue.get(), timeout=STREAM_KEEPALIVE_S
                )
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            async for view in _load_signal_views(pool, session_id, owner, sent_seq, signal):
                if view.seq > sent_seq:
                    sent_seq = view.seq
                    yield _sse_data(view)
    except asyncio.CancelledError:
        logger.debug("Session SSE client disconnected")
        raise
    finally:
        subscription.close()


async def _load_signal_views(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    session_id: str,
    owner: str,
    sent_seq: int,
    signal: SessionEventSignal,
) -> AsyncGenerator[SessionEventView]:
    if signal.last_seq is not None and signal.last_seq <= sent_seq:
        return
    to_seq = signal.last_seq
    async for view in _load_event_views(pool, session_id, owner, sent_seq + 1, to_seq):
        yield view


async def _load_event_views(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    session_id: str,
    owner: str,
    from_seq: int,
    to_seq: int | None,
) -> AsyncGenerator[SessionEventView]:
    next_seq = from_seq
    while True:
        async with pool.connection() as conn:
            rows = await AsyncSessionDao(conn).get_events_for_owner(
                session_id,
                owner=owner,
                from_seq=next_seq,
                to_seq=to_seq,
                limit=STREAM_FETCH_LIMIT,
            )
        if not rows:
            return
        for row in rows:
            yield SessionEventView.from_row(row)
        if len(rows) < STREAM_FETCH_LIMIT:
            return
        next_seq = rows[-1].seq + 1


async def _require_session(
    conn: AsyncConnection[DictRow], session_id: str, owner: str
) -> SessionRow:
    session = await AsyncSessionDao(conn).get_session_for_owner(session_id, owner=owner)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def _sse_data(view: SessionEventView) -> str:
    return f"data: {view.model_dump_json()}\n\n"
