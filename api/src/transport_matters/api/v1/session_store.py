"""Session store dependencies shared by API routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool


def optional_session_pool(
    request: Request,
) -> AsyncConnectionPool[AsyncConnection[DictRow]] | None:
    pool = getattr(request.app.state, "session_pool", None)
    if pool is None:
        return None
    return cast("AsyncConnectionPool[AsyncConnection[DictRow]]", pool)


def require_session_pool(
    request: Request,
) -> AsyncConnectionPool[AsyncConnection[DictRow]]:
    pool = optional_session_pool(request)
    if pool is None:
        raise HTTPException(status_code=503, detail="session store unavailable")
    return pool
