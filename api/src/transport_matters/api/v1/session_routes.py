"""FastAPI read surface for the Postgres session store."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from typing import TYPE_CHECKING, Annotated, Any, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from fastapi.responses import StreamingResponse

from transport_matters.api.v1.exchanges import exchange_detail_route
from transport_matters.api.v1.session_models import (
    DEFAULT_SESSIONS_LIMIT,
    MAX_SESSIONS_LIMIT,
    ApiError,
    ListSessionsResponse,
    SessionEventListResponse,
    SessionView,
    session_view_from_row,
    transcript_event_views,
    validate_session_purpose,
    validate_session_visibility,
)
from transport_matters.api.v1.session_store import optional_session_pool
from transport_matters.session.async_dao import AsyncSessionDao
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

    from transport_matters.session.models import SessionRow

    StreamBatchLoader = Callable[[int, int | None], AsyncGenerator[tuple[int, list[str]]]]
    StreamPage = tuple[int, int, list[str]]
    StreamPageFetcher = Callable[[int, int | None], Awaitable[StreamPage | None]]

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_OWNER = "local"
STREAM_KEEPALIVE_S = 15.0
STREAM_FETCH_LIMIT = 1000


async def _session_pool(request: Request) -> AsyncConnectionPool[AsyncConnection[DictRow]]:
    pool = optional_session_pool(request)
    if pool is None:
        _raise_api_error(
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
            "session_store_unavailable",
            "session store unavailable",
        )
    return pool


def _session_hub(request: Request) -> SessionEventHub:
    hub = getattr(request.app.state, "session_event_hub", None)
    if not isinstance(hub, SessionEventHub):
        raise HTTPException(status_code=503, detail="session event stream unavailable")
    return hub


def _response_payload(response: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", response.model_dump(mode="json", by_alias=True))


def _api_error(code: str, message: str, details: object | None = None) -> dict[str, object]:
    return _response_payload(ApiError(code=code, message=message, details=details))


def _raise_api_error(
    status_code: int, code: str, message: str, details: object | None = None
) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=_api_error(code, message, details))


def _not_found(session_id: str) -> NoReturn:
    _raise_api_error(
        http_status.HTTP_404_NOT_FOUND,
        "session_not_found",
        f"session {session_id!r} was not found",
    )


def _cursor_filter_key(
    *,
    owner: str,
    workspace_id: str | None,
    purpose: str | None,
    visibility: str | None,
    include_internal: bool,
) -> dict[str, object]:
    return {
        "owner": owner,
        "workspaceId": workspace_id,
        "purpose": purpose,
        "visibility": visibility,
        "includeInternal": include_internal,
    }


def _encode_cursor(offset: int, *, filters: dict[str, object]) -> str:
    raw = json.dumps({"offset": offset, "filters": filters}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, *, filters: dict[str, object]) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except binascii.Error, UnicodeDecodeError, ValueError, json.JSONDecodeError:
        _raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    if not isinstance(payload, dict):
        _raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    if payload.get("filters") != filters:
        _raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_cursor",
            "cursor does not match the active filters",
        )
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        _raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    return offset


@router.get("/sessions", response_model=ListSessionsResponse)
async def list_sessions(
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    workspace_id: Annotated[str | None, Query(alias="workspaceId")] = None,
    purpose: Annotated[str | None, Query()] = None,
    visibility: Annotated[str | None, Query()] = None,
    include_internal: Annotated[bool, Query(alias="includeInternal")] = False,
    limit: Annotated[int, Query(ge=1, le=MAX_SESSIONS_LIMIT)] = DEFAULT_SESSIONS_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    try:
        validated_purpose = validate_session_purpose(purpose)
        validated_visibility = validate_session_visibility(visibility)
    except ValueError as exc:
        _raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_request", str(exc))
    filters = _cursor_filter_key(
        owner=owner,
        workspace_id=workspace_id,
        purpose=validated_purpose,
        visibility=validated_visibility,
        include_internal=include_internal,
    )
    offset = _decode_cursor(cursor, filters=filters) if cursor is not None else 0
    async with pool.connection() as conn:
        dao = AsyncSessionDao(conn)
        rows = await dao.list_session_views(
            owner=owner,
            workspace_id=workspace_id,
            purpose=validated_purpose,
            visibility=validated_visibility,
            include_internal=include_internal,
            limit=limit + 1,
            offset=offset,
        )
    items = [session_view_from_row(row) for row in rows[:limit]]
    next_cursor = _encode_cursor(offset + limit, filters=filters) if len(rows) > limit else None
    return _response_payload(ListSessionsResponse(items=items, next_cursor=next_cursor))


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(
    session_id: str,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
) -> dict[str, object]:
    async with pool.connection() as conn:
        row = await AsyncSessionDao(conn).get_session_view_for_owner(session_id, owner=owner)
    if row is None:
        _not_found(session_id)
    return _response_payload(session_view_from_row(row))


@router.get("/sessions/{session_id}/events", response_model=SessionEventListResponse)
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
        dao = AsyncSessionDao(conn)
        turn_index_offset = await dao.count_turns_before_for_owner(
            session_id,
            owner=owner,
            before_seq=from_seq or 0,
        )
        rows = await dao.get_events_for_owner(
            session_id,
            owner=owner,
            from_seq=from_seq,
            to_seq=to_seq,
            limit=limit,
        )
    events = transcript_event_views(rows, turn_index_offset=turn_index_offset)
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
        turn_index_offset = await dao.count_turns_before_for_owner(
            session_id,
            owner=owner,
            before_seq=from_seq or 0,
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
        turn_index_offset=turn_index_offset,
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
                "route": exchange_detail_route(content.exchange_id, run_id=content.run_id),
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
            dao = AsyncSessionDao(conn)
            turn_index_offset = await dao.count_turns_before_for_owner(
                session_id,
                owner=owner,
                before_seq=next_seq,
            )
            rows = await dao.get_events_for_owner(
                session_id,
                owner=owner,
                from_seq=next_seq,
                to_seq=page_to_seq,
                limit=STREAM_FETCH_LIMIT,
            )
        if not rows:
            return None
        events = transcript_event_views(rows, turn_index_offset=turn_index_offset)
        return rows[-1].seq, len(rows), [_sse_data(event) for event in events]

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
            projection_from_seq = projection_rows[0].seq if projection_rows else next_seq
            turn_index_offset = await dao.count_turns_before_for_owner(
                session.session_id,
                owner=owner,
                before_seq=projection_from_seq,
            )
        envelopes = project_timeline_stream_envelopes(
            session=session,
            events=projection_rows,
            child_sessions=child_sessions,
            include_session_update=False,
            page_from_seq=next_seq,
            turn_index_offset=turn_index_offset,
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
        _not_found(session_id)
    return session


def _sse_data(payload: Any | TimelineStreamEnvelope) -> str:
    return f"data: {payload.model_dump_json(by_alias=True)}\n\n"
