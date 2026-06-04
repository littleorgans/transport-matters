"""Tier-2 read/query HTTP surface (prefix ``/api/index``, §8.7). Thin wrappers over queries.py.

Server layer (after ``index`` in the DAG): may import ``index`` + ``queries``. Each request
borrows a short-lived read-only connection (``query_only = ON``, §8.1) via ``_read_connection``;
when no index.db exists yet (tier-2 never started) the endpoints return empty rather than 500.
Raw bytes are always streamed from tier-1; tier-2 stores none (§8.5).
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from transport_matters.index.db import connect, index_db_path
from transport_matters.index.models import (
    BlockBody,
    BlockHit,
    Correspondence,
    SearchFilters,
    SessionDiff,
    SessionFilters,
    SessionRow,
    TimelineEntry,
)
from transport_matters.index.queries import (
    exchange_raw_ref,
    get_block_bodies,
    list_sessions,
    search_blocks,
    session_diff,
    session_pivot,
    session_timeline,
)

router = APIRouter()


def _read_connection() -> Iterator[sqlite3.Connection | None]:
    """Yield a short-lived read-only connection, or ``None`` when no index.db exists yet (§8.1)."""
    path = index_db_path()
    if not path.exists():
        yield None
        return
    conn = connect(path, read_only=True)
    try:
        yield conn
    finally:
        conn.close()


_ReadConn = Annotated[sqlite3.Connection | None, Depends(_read_connection)]


class SearchRequest(BaseModel):
    q: str
    filters: SearchFilters = Field(default_factory=SearchFilters)
    mode: Literal["occurrence", "block"] = "occurrence"
    limit: int = 50
    offset: int = 0
    expand_ids: list[int] = Field(default_factory=list)


class SearchResponse(BaseModel):
    hits: list[BlockHit]
    bodies: list[BlockBody]


class BlocksRequest(BaseModel):
    ids: list[int]


@router.post("/search")
def search(body: SearchRequest, conn: _ReadConn) -> SearchResponse:
    if conn is None:
        return SearchResponse(hits=[], bodies=[])
    hits = search_blocks(
        conn, body.q, filters=body.filters, mode=body.mode, limit=body.limit, offset=body.offset
    )
    bodies = get_block_bodies(conn, body.expand_ids) if body.expand_ids else []
    return SearchResponse(hits=hits, bodies=bodies)


@router.post("/blocks")
def blocks(body: BlocksRequest, conn: _ReadConn) -> list[BlockBody]:
    return get_block_bodies(conn, body.ids) if conn is not None else []


@router.get("/sessions")
def sessions(
    conn: _ReadConn,
    workspace_hash: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    cli: Annotated[str | None, Query()] = None,
) -> list[SessionRow]:
    if conn is None:
        return []
    filters = SessionFilters(
        workspace_hash=workspace_hash, run_id=run_id, provider=provider, cli=cli
    )
    return list_sessions(conn, filters=filters)


@router.get("/sessions/{session_id}/timeline")
def timeline(
    session_id: str,
    conn: _ReadConn,
    stream: Literal["wire", "transcript"] = "wire",
    with_bodies: bool = False,
    seq_from: int | None = None,
    seq_to: int | None = None,
) -> list[TimelineEntry]:
    if conn is None:
        return []
    return session_timeline(
        conn, session_id, stream=stream, with_bodies=with_bodies, seq_from=seq_from, seq_to=seq_to
    )


@router.get("/sessions/{session_id}/pivot")
def pivot(session_id: str, conn: _ReadConn) -> list[Correspondence]:
    return session_pivot(conn, session_id) if conn is not None else []


@router.get("/sessions/{session_id}/diff")
def diff(session_id: str, conn: _ReadConn) -> SessionDiff:
    if conn is None:
        return SessionDiff(wire_only=[], transcript_only=[], shared=[])
    return session_diff(conn, session_id)


@router.get("/exchanges/{exchange_id}/raw")
def raw(
    exchange_id: str, conn: _ReadConn, part: Literal["request", "response"] = "request"
) -> FileResponse:
    if conn is None:
        raise HTTPException(status_code=404, detail="index unavailable")
    try:
        ref = exchange_raw_ref(conn, exchange_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="exchange not found") from None
    path = Path(ref.request_raw if part == "request" else ref.response_raw)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{part} raw bytes not found")
    return FileResponse(path)
