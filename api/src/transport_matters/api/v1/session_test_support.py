from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from httpx import ASGITransport, AsyncClient

from transport_matters.main import create_app
from transport_matters.session.listen import SessionEventHub
from transport_matters.session.pool import create_async_pool
from transport_matters.session.testing import TestDb

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def session_client(test_db: TestDb) -> AsyncIterator[AsyncClient]:
    pool = create_async_pool(test_db.database_url, min_size=1, max_size=4)
    await pool.open()
    app = create_app()
    app.state.session_pool = pool
    app.state.session_event_hub = SessionEventHub()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        await pool.close()
