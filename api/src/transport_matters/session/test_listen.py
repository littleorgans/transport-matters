from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from transport_matters.index.conftest import make_binding
from transport_matters.session.ingest import EventWrite, build_event_batch
from transport_matters.session.listen import (
    SessionEventHub,
    SessionEventListener,
    SessionEventSignal,
    parse_notify_payload,
)
from transport_matters.session.pool import async_connect
from transport_matters.session.test_foundation import event
from transport_matters.session.writer import _notify_payload

if TYPE_CHECKING:
    from collections.abc import Callable

    from transport_matters.session.testing import TestDb


def test_writer_notify_payload_is_small_session_range_handle() -> None:
    payload = _notify_payload(
        build_event_batch(
            make_binding("s1"),
            [EventWrite(event=event(0, session_id="s1"))],
        )
    )
    data = json.loads(payload)

    assert set(data) == {"count", "first_seq", "last_seq", "run_id", "session_id", "type"}
    assert "raw" not in data
    assert "ir" not in data
    assert len(payload.encode()) < 8000
    assert parse_notify_payload(payload) == SessionEventSignal(
        session_id="s1", first_seq=0, last_seq=0
    )


async def test_session_event_listener_reconnects_after_dropped_connection(test_db: TestDb) -> None:
    hub = SessionEventHub()
    subscription = hub.subscribe("s1")
    listener = SessionEventListener(
        test_db.database_url,
        hub,
        reconnect_delay_s=0.05,
        notify_timeout_s=0.05,
    )
    await listener.start()
    try:
        first_pid = await _wait_for_pid(lambda: listener.connection_pid)
        await _terminate_backend(test_db.database_url, first_pid)
        second_pid = await _wait_for_pid(lambda: listener.connection_pid, previous=first_pid)

        assert second_pid != first_pid
        await _notify(
            test_db.database_url,
            '{"type":"session_events","session_id":"s1","first_seq":3,"last_seq":3}',
        )
        signal = await asyncio.wait_for(subscription.queue.get(), timeout=2.0)
        assert signal == SessionEventSignal(session_id="s1", first_seq=3, last_seq=3)
    finally:
        subscription.close()
        await listener.aclose()


async def test_session_event_listener_close_releases_connection(test_db: TestDb) -> None:
    listener = SessionEventListener(test_db.database_url, SessionEventHub(), notify_timeout_s=0.05)
    await listener.start()
    pid = await _wait_for_pid(lambda: listener.connection_pid)

    await listener.aclose()

    assert await _wait_for_backend_gone(test_db.database_url, pid)


async def _wait_for_pid(get_pid: Callable[[], int | None], *, previous: int | None = None) -> int:
    for _ in range(100):
        pid = get_pid()
        if pid is not None and pid != previous:
            return pid
        await asyncio.sleep(0.05)
    raise AssertionError("listener did not expose a connection pid")


async def _terminate_backend(database_url: str, pid: int) -> None:
    async with await async_connect(database_url, autocommit=True) as conn:
        await conn.execute("SELECT pg_terminate_backend(%s)", (pid,))


async def _notify(database_url: str, payload: str) -> None:
    async with await async_connect(database_url, autocommit=True) as conn:
        await conn.execute("SELECT pg_notify('tm_events', %s)", (payload,))


async def _wait_for_backend_gone(database_url: str, pid: int) -> bool:
    for _ in range(100):
        if not await _backend_exists(database_url, pid):
            return True
        await asyncio.sleep(0.05)
    return False


async def _backend_exists(database_url: str, pid: int) -> bool:
    async with await async_connect(database_url, autocommit=True) as conn:
        cursor = await conn.execute(
            "SELECT count(*) AS n FROM pg_stat_activity WHERE pid = %s",
            (pid,),
        )
        row = await cursor.fetchone()
    assert row is not None
    return int(row["n"]) > 0
