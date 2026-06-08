"""FastAPI read surface for the Postgres session store."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from transport_matters.api.v1.exchanges import exchange_detail_route
from transport_matters.session.dao import AsyncSessionDao
from transport_matters.session.listen import SessionEventHub
from transport_matters.session.resource_content import load_resource_content
from transport_matters.session.resource_content_models import (
    ExchangeRedirectDescriptor,
    ExchangeRedirectResponse,
    ResourceContentResolutionType,
    ResourceContentResponse,
    ResourceContentResponseType,
)
from transport_matters.session.timeline import project_timeline, required_timeline_anchor_before_seq
from transport_matters.session.timeline_models import TimelineResponse, TimelineStreamEnvelope
from transport_matters.session.timeline_stream import project_timeline_stream_envelopes

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from psycopg import AsyncConnection
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool

    from transport_matters.session.models import EventReadRow, EventRow, SessionRow

    StreamBatchLoader = Callable[[int, int | None], AsyncGenerator[tuple[int, list[str]]]]
    StreamPage = tuple[int, int, list[str]]
    StreamPageFetcher = Callable[[int, int | None], Awaitable[StreamPage | None]]

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
    def from_row(cls, row: EventReadRow | EventRow) -> SessionEventView:
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


@router.get("/sessions/{session_id}/timeline", response_model=TimelineResponse)
async def get_session_timeline(
    session_id: str,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    from_seq: Annotated[int | None, Query(ge=0)] = None,
    to_seq: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    include_resources: bool = True,
    include_debug: bool = False,
) -> TimelineResponse:
    async with pool.connection() as conn:
        session = await _require_session(conn, session_id, owner)
        dao = AsyncSessionDao(conn)
        rows = await dao.get_events_with_raw_for_owner(
            session_id,
            owner=owner,
            from_seq=from_seq,
            to_seq=to_seq,
            limit=limit,
        )
        child_sessions = await dao.list_child_sessions_for_owner(session_id, owner=owner)
    next_from_seq = rows[-1].seq + 1 if len(rows) == limit else None
    return project_timeline(
        session=session,
        events=rows,
        child_sessions=child_sessions,
        include_resources=include_resources,
        include_debug=include_debug,
        page_from_seq=from_seq,
        next_from_seq=next_from_seq,
    )


@router.get(
    "/sessions/{session_id}/resources/{resource_id}",
    response_model=ResourceContentResponse,
)
async def get_session_resource(
    session_id: str,
    resource_id: str,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    range_start: Annotated[int | None, Query(ge=0)] = None,
    range_end: Annotated[int | None, Query(ge=0)] = None,
    include_debug: bool = False,
) -> ResourceContentResponse:
    async with pool.connection() as conn:
        session = await _require_session(conn, session_id, owner)
        content = await load_resource_content(
            conn,
            session=session,
            owner=owner,
            resource_id=resource_id,
            range_start=range_start,
            range_end=range_end,
            include_debug=include_debug,
        )
    return _api_resource_content_response(content)


def _api_resource_content_response(
    content: ResourceContentResolutionType,
) -> ResourceContentResponseType:
    if isinstance(content, ExchangeRedirectDescriptor):
        return ExchangeRedirectResponse.model_validate(
            {
                **content.model_dump(),
                "route": exchange_detail_route(content.exchange_id),
            }
        )
    return content


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


@router.get("/sessions/{session_id}/timeline/stream")
async def stream_session_timeline(
    session_id: str,
    pool: Any = Depends(_session_pool),
    hub: SessionEventHub = Depends(_session_hub),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    last_seq: Annotated[int, Query(ge=-1)] = -1,
) -> StreamingResponse:
    async with pool.connection() as conn:
        session = await _require_session(conn, session_id, owner)
    generator = _timeline_stream(session, owner, last_seq, pool, hub)
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
    async def load_batches(
        from_seq: int, to_seq: int | None
    ) -> AsyncGenerator[tuple[int, list[str]]]:
        async for batch in _load_event_frame_batches(pool, session_id, owner, from_seq, to_seq):
            yield batch

    async for frame in _stream_session_frames(
        session_id,
        last_seq,
        hub,
        load_batches=load_batches,
    ):
        yield frame


async def _timeline_stream(
    session: SessionRow,
    owner: str,
    last_seq: int,
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    hub: SessionEventHub,
) -> AsyncGenerator[str]:
    # Slice 2 emits the session snapshot at connect. Live session only changes need
    # a session level signal and are deferred with the slice 4 parentless update work.
    envelopes = project_timeline_stream_envelopes(
        session=session,
        events=[],
        include_session_update=True,
    )
    for envelope in envelopes:
        yield _sse_data(envelope)

    async def load_batches(
        from_seq: int, to_seq: int | None
    ) -> AsyncGenerator[tuple[int, list[str]]]:
        async for batch in _load_timeline_frame_batches(pool, session, owner, from_seq, to_seq):
            yield batch

    async for frame in _stream_session_frames(
        session.session_id,
        last_seq,
        hub,
        load_batches=load_batches,
    ):
        yield frame


async def _stream_session_frames(
    session_id: str,
    last_seq: int,
    hub: SessionEventHub,
    *,
    load_batches: StreamBatchLoader,
) -> AsyncGenerator[str]:
    subscription = hub.subscribe(session_id)
    sent_seq = last_seq
    try:
        async for batch_seq, frames in load_batches(sent_seq + 1, None):
            if batch_seq > sent_seq:
                for frame in frames:
                    yield frame
                sent_seq = batch_seq
        while True:
            try:
                signal = await asyncio.wait_for(
                    subscription.queue.get(), timeout=STREAM_KEEPALIVE_S
                )
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if signal.last_seq is not None and signal.last_seq <= sent_seq:
                continue
            async for batch_seq, frames in load_batches(sent_seq + 1, signal.last_seq):
                if batch_seq > sent_seq:
                    for frame in frames:
                        yield frame
                    sent_seq = batch_seq
    except asyncio.CancelledError:
        logger.debug("Session SSE client disconnected")
        raise
    finally:
        subscription.close()


async def _load_event_frame_batches(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    session_id: str,
    owner: str,
    from_seq: int,
    to_seq: int | None,
) -> AsyncGenerator[tuple[int, list[str]]]:
    async def fetch_page(
        next_seq: int, page_to_seq: int | None
    ) -> tuple[int, int, list[str]] | None:
        async with pool.connection() as conn:
            rows = await AsyncSessionDao(conn).get_events_for_owner(
                session_id,
                owner=owner,
                from_seq=next_seq,
                to_seq=page_to_seq,
                limit=STREAM_FETCH_LIMIT,
            )
        if not rows:
            return None
        return rows[-1].seq, len(rows), [_sse_data(SessionEventView.from_row(row)) for row in rows]

    async for batch in _paginate_seq(from_seq, to_seq, fetch_page):
        yield batch


async def _load_timeline_frame_batches(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    session: SessionRow,
    owner: str,
    from_seq: int,
    to_seq: int | None,
) -> AsyncGenerator[tuple[int, list[str]]]:
    async def fetch_page(
        next_seq: int, page_to_seq: int | None
    ) -> tuple[int, int, list[str]] | None:
        async with pool.connection() as conn:
            dao = AsyncSessionDao(conn)
            rows = await dao.get_events_with_raw_for_owner(
                session.session_id,
                owner=owner,
                from_seq=next_seq,
                to_seq=page_to_seq,
                limit=STREAM_FETCH_LIMIT,
            )
            if not rows:
                # Slice 4 owns subagent/resource changes that arrive without a new parent event.
                # This event driven stream has no row to project for those updates.
                return None
            anchor_before_seq = required_timeline_anchor_before_seq(rows)
            anchor = (
                await dao.get_latest_turn_before_with_raw_for_owner(
                    session.session_id,
                    owner=owner,
                    before_seq=anchor_before_seq,
                )
                if anchor_before_seq is not None
                else None
            )
            child_sessions = await dao.list_child_sessions_for_owner(
                session.session_id, owner=owner
            )
        projection_rows = [anchor, *rows] if anchor is not None else rows
        envelopes = project_timeline_stream_envelopes(
            session=session,
            events=projection_rows,
            child_sessions=child_sessions,
            include_session_update=False,
            page_from_seq=next_seq,
        )
        return rows[-1].seq, len(rows), [_sse_data(envelope) for envelope in envelopes]

    async for batch in _paginate_seq(from_seq, to_seq, fetch_page):
        yield batch


async def _paginate_seq(
    from_seq: int,
    to_seq: int | None,
    fetch_page: StreamPageFetcher,
) -> AsyncGenerator[tuple[int, list[str]]]:
    next_seq = from_seq
    while True:
        page = await fetch_page(next_seq, to_seq)
        if page is None:
            return
        batch_seq, row_count, frames = page
        yield batch_seq, frames
        if row_count < STREAM_FETCH_LIMIT:
            return
        next_seq = batch_seq + 1


async def _require_session(
    conn: AsyncConnection[DictRow], session_id: str, owner: str
) -> SessionRow:
    session = await AsyncSessionDao(conn).get_session_for_owner(session_id, owner=owner)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def _sse_data(payload: SessionEventView | TimelineStreamEnvelope) -> str:
    return f"data: {payload.model_dump_json(by_alias=True)}\n\n"
