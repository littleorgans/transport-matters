from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters.config import get_settings
from transport_matters.main import create_app, lifespan
from transport_matters.session.dao import AsyncSessionDao
from transport_matters.session.listen import (
    SessionEventHub,
    SessionEventListener,
    SessionEventSignal,
)
from transport_matters.session.pool import async_connect, create_async_pool
from transport_matters.session.test_foundation import event, root_session
from transport_matters.session.testing import TestDb
from transport_matters.session.timeline import project_timeline

from .session_routes import _event_stream, _timeline_stream

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from psycopg import AsyncConnection
    from psycopg.rows import DictRow


@pytest.fixture
def test_db() -> Iterator[TestDb]:
    db = TestDb.create()
    try:
        yield db
    finally:
        db.drop()


@asynccontextmanager
async def _client(test_db: TestDb) -> AsyncIterator[AsyncClient]:
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


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


async def test_session_routes_are_owner_scoped_and_omit_raw(test_db: TestDb) -> None:
    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        await _seed_sessions(conn)
    async with _client(test_db) as client:
        sessions = await client.get("/api/sessions")
        assert sessions.status_code == 200
        assert [item["session_id"] for item in sessions.json()] == ["s1"]

        other = await client.get("/api/sessions", params={"owner": "other"})
        assert other.status_code == 200
        assert [item["session_id"] for item in other.json()] == ["s2"]

        events = await client.get("/api/sessions/s1/events", params={"limit": 1})
        assert events.status_code == 200
        payload = events.json()
        assert payload["next_from_seq"] == 1
        assert [item["seq"] for item in payload["events"]] == [0]
        assert payload["events"][0]["ir"] == {"parts": [{"type": "text", "text": "alpha"}]}
        assert "raw" not in payload["events"][0]

        hidden = await client.get("/api/sessions/s1/events", params={"owner": "other"})
        assert hidden.status_code == 404


async def test_session_timeline_is_owner_scoped_paginated_and_omits_raw(
    test_db: TestDb,
) -> None:
    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        dao = AsyncSessionDao(conn)
        await dao.upsert_session(root_session("s1", native_session_id="native1"))
        await dao.upsert_session(
            root_session("s2", native_session_id="native2").model_copy(update={"owner": "other"})
        )
        await dao.insert_event(event(0, session_id="s1", search_text="alpha"))
        await dao.insert_event(
            event(1, session_id="s1", search_text="permission").model_copy(
                update={
                    "kind": "meta",
                    "raw": {"type": "permission-mode", "mode": "plan"},
                    "ir": None,
                    "role": None,
                }
            )
        )
        await dao.insert_event(event(0, session_id="s2", search_text="other"))

    async with _client(test_db) as client:
        first = await client.get("/api/sessions/s1/timeline", params={"limit": 1})
        assert first.status_code == 200
        first_payload = first.json()
        assert first_payload["session"]["sessionId"] == "s1"
        assert first_payload["nextFromSeq"] == 1
        assert [item["kind"] for item in first_payload["items"]] == ["message"]
        assert first_payload["items"][0]["source"]["rawAvailable"] is True
        assert not _contains_key(first_payload, "raw")

        second = await client.get("/api/sessions/s1/timeline", params={"from_seq": 1, "limit": 1})
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["nextFromSeq"] == 2
        assert [(item["kind"], item["label"]) for item in second_payload["items"]] == [
            ("state", "Permission mode")
        ]

        hidden = await client.get("/api/sessions/s1/timeline", params={"owner": "other"})
        assert hidden.status_code == 404


async def test_session_event_stream_backlog_then_live_dedups_race(test_db: TestDb) -> None:
    hub = SessionEventHub()
    async with create_async_pool(test_db.database_url, min_size=1, max_size=3) as pool:
        async with pool.connection() as conn:
            dao = AsyncSessionDao(conn)
            await dao.upsert_session(root_session("s1"))
            await dao.insert_event(event(0, session_id="s1", search_text="first"))

        stream = _event_stream("s1", "local", -1, pool, hub)
        first_frame_task = asyncio.create_task(anext(stream))
        await _wait_for(lambda: hub.subscriber_count("s1") == 1)
        async with pool.connection() as conn:
            await AsyncSessionDao(conn).insert_event(
                event(1, session_id="s1", search_text="second")
            )
        signal = SessionEventSignal(session_id="s1", first_seq=1, last_seq=1)
        hub.publish(signal)
        hub.publish(signal)

        try:
            first = _frame_payload(await asyncio.wait_for(first_frame_task, timeout=2.0))
            second = _frame_payload(await asyncio.wait_for(anext(stream), timeout=2.0))
            assert [first["seq"], second["seq"]] == [0, 1]
            try:
                await asyncio.wait_for(anext(stream), timeout=0.2)
            except TimeoutError:
                pass
            else:
                raise AssertionError("duplicate SSE event emitted")
        finally:
            await stream.aclose()


async def test_session_event_stream_catches_up_after_listener_reconnect_gap(
    test_db: TestDb,
) -> None:
    hub = SessionEventHub()
    listener = SessionEventListener(
        test_db.database_url,
        hub,
        reconnect_delay_s=0.2,
        notify_timeout_s=0.05,
    )
    async with create_async_pool(test_db.database_url, min_size=1, max_size=3) as pool:
        async with pool.connection() as conn:
            dao = AsyncSessionDao(conn)
            await dao.upsert_session(root_session("s1"))
            await dao.insert_event(event(0, session_id="s1", search_text="first"))

        await listener.start()
        stream = _event_stream("s1", "local", -1, pool, hub)
        try:
            first = _frame_payload(await asyncio.wait_for(anext(stream), timeout=2.0))
            assert first["seq"] == 0

            first_pid = await _wait_for_pid(lambda: listener.connection_pid)
            await _terminate_backend(test_db.database_url, first_pid)
            assert await _wait_for(lambda: listener.connection_pid is None)

            async with pool.connection() as conn:
                await AsyncSessionDao(conn).insert_event(
                    event(1, session_id="s1", search_text="during reconnect")
                )

            second_pid = await _wait_for_pid(lambda: listener.connection_pid, previous=first_pid)
            assert second_pid != first_pid
            second = _frame_payload(await asyncio.wait_for(anext(stream), timeout=2.0))
            assert second["seq"] == 1
        finally:
            await stream.aclose()
            await listener.aclose()


async def test_session_timeline_stream_emits_live_item_with_stable_id(
    test_db: TestDb,
) -> None:
    hub = SessionEventHub()
    async with create_async_pool(test_db.database_url, min_size=1, max_size=3) as pool:
        async with pool.connection() as conn:
            await AsyncSessionDao(conn).upsert_session(root_session("s1"))

        stream = _timeline_stream(root_session("s1"), "local", -1, pool, hub)
        try:
            session_frame = _frame_payload(await asyncio.wait_for(anext(stream), timeout=2.0))
            assert session_frame["id"] == "session:s1"
            session_event = cast("dict[str, object]", session_frame["event"])
            assert session_event["kind"] == "session-updated"

            timeline_frame_task = asyncio.create_task(anext(stream))
            await _wait_for(lambda: hub.subscriber_count("s1") == 1)
            async with pool.connection() as conn:
                await AsyncSessionDao(conn).insert_event(
                    event(0, session_id="s1", search_text="live")
                )
            hub.publish(SessionEventSignal(session_id="s1", first_seq=0, last_seq=0))

            timeline_frame = _frame_payload(
                await asyncio.wait_for(timeline_frame_task, timeout=2.0)
            )
            assert timeline_frame["id"] == "timeline:s1:0"
            assert timeline_frame["revision"] == 0
            timeline_event = cast("dict[str, object]", timeline_frame["event"])
            timeline_item = cast("dict[str, object]", timeline_event["item"])
            assert timeline_event["kind"] == "timeline-item"
            assert timeline_item["id"] == "message:s1:0"
            assert timeline_event["resources"] == {
                "native:s1:0": {
                    "kind": "native-record",
                    "id": "native:s1:0",
                    "title": "Native record",
                    "source": timeline_item["source"],
                }
            }
        finally:
            await stream.aclose()


async def test_session_timeline_stream_reemits_enriched_prior_item(
    test_db: TestDb,
) -> None:
    hub = SessionEventHub()
    turn = event(0, session_id="s1", search_text="stdout")
    duration = event(1, session_id="s1").model_copy(
        update={
            "kind": "meta",
            "raw": {"type": "system", "subtype": "turn_duration", "ms": 42},
            "ir": None,
            "role": None,
        }
    )
    backlog = project_timeline(session=root_session("s1"), events=[turn, duration])
    resource_id = "native:s1:0"

    async with create_async_pool(test_db.database_url, min_size=1, max_size=3) as pool:
        async with pool.connection() as conn:
            await AsyncSessionDao(conn).upsert_session(root_session("s1"))

        stream = _timeline_stream(root_session("s1"), "local", -1, pool, hub)
        try:
            session_frame = _frame_payload(await asyncio.wait_for(anext(stream), timeout=2.0))
            assert session_frame["id"] == "session:s1"

            first_task = asyncio.create_task(anext(stream))
            await _wait_for(lambda: hub.subscriber_count("s1") == 1)
            async with pool.connection() as conn:
                await AsyncSessionDao(conn).insert_event(turn)
            hub.publish(SessionEventSignal(session_id="s1", first_seq=0, last_seq=0))

            first_frame = _frame_payload(await asyncio.wait_for(first_task, timeout=2.0))
            assert first_frame["id"] == "timeline:s1:0"
            resource_frame = _frame_payload(await asyncio.wait_for(anext(stream), timeout=2.0))
            assert resource_frame["id"] == f"resource:s1:{resource_id}"

            update_task = asyncio.create_task(anext(stream))
            async with pool.connection() as conn:
                await AsyncSessionDao(conn).insert_event(duration)
            hub.publish(SessionEventSignal(session_id="s1", first_seq=1, last_seq=1))

            update_frame = _frame_payload(await asyncio.wait_for(update_task, timeout=2.0))
            update_event = cast("dict[str, object]", update_frame["event"])
            update_item = cast("dict[str, object]", update_event["item"])
            assert update_frame["id"] == "timeline:s1:0"
            assert update_frame["revision"] == 1
            assert update_item["badges"] == [
                {"label": "Turn duration", "value": "42 ms", "tone": "neutral"}
            ]
            assert update_event["resources"] == {
                resource_id: backlog.resources[resource_id].model_dump(mode="json", by_alias=True)
            }
        finally:
            await stream.aclose()


async def test_session_timeline_stream_is_owner_scoped(test_db: TestDb) -> None:
    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        await AsyncSessionDao(conn).upsert_session(root_session("s1"))

    async with _client(test_db) as client:
        hidden = await client.get("/api/sessions/s1/timeline/stream", params={"owner": "other"})

    assert hidden.status_code == 404


async def test_app_lifespan_releases_session_listener_connection(
    test_db: TestDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRANSPORT_MATTERS_DATABASE_URL", test_db.database_url)
    get_settings.cache_clear()
    app = create_app()
    async with lifespan(app):
        listener = app.state.session_event_listener
        assert isinstance(listener, SessionEventListener)
        listener_pid = await _wait_for_pid(lambda: listener.connection_pid)
    try:
        assert await _wait_for_backend_gone(test_db.database_url, listener_pid)
    finally:
        get_settings.cache_clear()


async def test_lifespan_listener_start_failure_keeps_routes_unavailable(
    test_db: TestDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingListener:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.closed = False

        async def start(self) -> None:
            raise RuntimeError("listener failed")

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setenv("TRANSPORT_MATTERS_DATABASE_URL", test_db.database_url)
    monkeypatch.setattr("transport_matters.main.SessionEventListener", FailingListener)
    get_settings.cache_clear()
    app = create_app()
    try:
        async with lifespan(app):
            assert app.state.session_pool is None
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/sessions")
            assert response.status_code == 503
    finally:
        get_settings.cache_clear()


async def test_lifespan_degrades_when_database_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A configured-but-unreachable store must DEGRADE (503), not crash backend startup.
    # The launch-path preflight hard-blocks unreachable stores; this is the hosted/server
    # layer where the contract is degrade-not-crash.
    monkeypatch.setenv("TRANSPORT_MATTERS_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/none")
    get_settings.cache_clear()
    app = create_app()
    try:
        async with lifespan(app):
            assert app.state.session_pool is None
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/sessions")
            assert response.status_code == 503
    finally:
        get_settings.cache_clear()


def test_main_app_is_built_lazily_not_at_import() -> None:
    # Regression (collection isolation): importing main must NOT create the app at import
    # (which would call Settings.load() and read the operator's real settings.toml). The
    # lazy module __getattr__ builds a fresh app per access, proving none is bound eagerly.
    from fastapi import FastAPI

    import transport_matters.main as main_module

    first = main_module.app
    second = main_module.app
    assert isinstance(first, FastAPI)
    assert first is not second


async def test_lifespan_fails_fast_on_migration_failure(
    test_db: TestDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A CONFIRMED migration failure on a reachable DB must fail-fast (not degrade).
    from transport_matters.session.migrate import MigrationError

    def _broken_migration(_database_url: str) -> None:
        raise MigrationError("schema upgrade failed")

    monkeypatch.setenv("TRANSPORT_MATTERS_DATABASE_URL", test_db.database_url)
    monkeypatch.setattr("transport_matters.main.apply_migrations", _broken_migration)
    get_settings.cache_clear()
    app = create_app()
    try:
        with pytest.raises(MigrationError):
            async with lifespan(app):
                pass
    finally:
        get_settings.cache_clear()


async def _seed_sessions(conn: AsyncConnection[DictRow]) -> None:
    dao = AsyncSessionDao(conn)
    await dao.upsert_session(root_session("s1", native_session_id="native1"))
    await dao.upsert_session(
        root_session("s2", native_session_id="native2").model_copy(update={"owner": "other"})
    )
    await dao.insert_event(event(0, session_id="s1", search_text="alpha"))
    await dao.insert_event(
        event(1, session_id="s1", search_text="meta").model_copy(
            update={"kind": "meta", "raw": {"type": "session_meta"}, "ir": None, "role": None}
        )
    )
    await dao.insert_event(event(0, session_id="s2", search_text="other"))


def _frame_payload(frame: str) -> dict[str, object]:
    assert frame.startswith("data: ")
    return cast("dict[str, object]", json.loads(frame.removeprefix("data: ").strip()))


async def _wait_for(predicate: Callable[[], bool]) -> bool:
    for _ in range(100):
        if predicate():
            return True
        await asyncio.sleep(0.05)
    raise AssertionError("condition was not met")


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


async def _wait_for_backend_gone(database_url: str, pid: int) -> bool:
    for _ in range(100):
        async with await async_connect(database_url, autocommit=True) as conn:
            cursor = await conn.execute(
                "SELECT count(*) AS n FROM pg_stat_activity WHERE pid = %s",
                (pid,),
            )
            row = await cursor.fetchone()
        assert row is not None
        if int(row["n"]) == 0:
            return True
        await asyncio.sleep(0.05)
    return False
