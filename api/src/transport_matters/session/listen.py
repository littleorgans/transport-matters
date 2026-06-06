"""Postgres LISTEN/NOTIFY bridge for session event streams."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from psycopg import sql
from pydantic import BaseModel, ConfigDict

from transport_matters.session.pool import async_connect

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg.rows import DictRow

logger = logging.getLogger(__name__)

NOTIFY_CHANNEL = "tm_events"
QUEUE_MAX_SIZE = 1000


class SessionEventSignal(BaseModel):
    """Small committed-event handle delivered by Postgres NOTIFY."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    first_seq: int | None = None
    last_seq: int | None = None


@dataclass(slots=True)
class SessionEventSubscription:
    session_id: str
    queue: asyncio.Queue[SessionEventSignal]
    _hub: SessionEventHub
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._hub.unsubscribe(self)


class SessionEventHub:
    """In-process fanout keyed by session_id."""

    def __init__(self, *, queue_max_size: int = QUEUE_MAX_SIZE) -> None:
        self._queue_max_size = queue_max_size
        self._subscribers: dict[str, set[asyncio.Queue[SessionEventSignal]]] = {}

    def subscribe(self, session_id: str) -> SessionEventSubscription:
        queue: asyncio.Queue[SessionEventSignal] = asyncio.Queue(maxsize=self._queue_max_size)
        self._subscribers.setdefault(session_id, set()).add(queue)
        return SessionEventSubscription(session_id=session_id, queue=queue, _hub=self)

    def unsubscribe(self, subscription: SessionEventSubscription) -> None:
        queues = self._subscribers.get(subscription.session_id)
        if queues is None:
            return
        queues.discard(subscription.queue)
        if not queues:
            self._subscribers.pop(subscription.session_id, None)

    def publish(self, signal: SessionEventSignal) -> None:
        for queue in list(self._subscribers.get(signal.session_id, set())):
            try:
                queue.put_nowait(signal)
            except asyncio.QueueFull:
                logger.warning(
                    "Dropped session SSE event for %s because subscriber queue is full",
                    signal.session_id,
                )

    def publish_payload(self, payload: str) -> None:
        signal = parse_notify_payload(payload)
        if signal is not None:
            self.publish(signal)

    def publish_catch_up(self) -> None:
        for session_id in list(self._subscribers):
            self.publish(SessionEventSignal(session_id=session_id))

    def subscriber_count(self, session_id: str) -> int:
        return len(self._subscribers.get(session_id, set()))


class SessionEventListener:
    """Own one long-lived async connection that LISTENs for session event commits."""

    def __init__(
        self,
        database_url: str,
        hub: SessionEventHub,
        *,
        channel: str = NOTIFY_CHANNEL,
        reconnect_delay_s: float = 0.25,
        notify_timeout_s: float = 0.5,
    ) -> None:
        self._database_url = database_url
        self._hub = hub
        self._channel = channel
        self._reconnect_delay_s = reconnect_delay_s
        self._notify_timeout_s = notify_timeout_s
        self._task: asyncio.Task[None] | None = None
        self._closing = False
        self._conn: AsyncConnection[DictRow] | None = None
        self._connection_pid: int | None = None

    @property
    def connection_pid(self) -> int | None:
        return self._connection_pid

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._closing = False
        self._task = asyncio.create_task(self._run(), name="session-event-listener")

    async def aclose(self) -> None:
        self._closing = True
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._closing:
            try:
                await self._listen_forever()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Session event listener dropped; reconnecting")
                await asyncio.sleep(self._reconnect_delay_s)

    async def _listen_forever(self) -> None:
        conn = await async_connect(self._database_url, autocommit=True)
        self._conn = conn
        self._connection_pid = await _connection_pid(conn)
        try:
            await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(self._channel)))
            self._hub.publish_catch_up()
            while not self._closing:
                async for notify in conn.notifies(timeout=self._notify_timeout_s):
                    self._hub.publish_payload(notify.payload)
        finally:
            self._connection_pid = None
            self._conn = None
            await conn.close()


async def _connection_pid(conn: AsyncConnection[DictRow]) -> int:
    cursor = await conn.execute("SELECT pg_backend_pid() AS pid")
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("could not read listener connection pid")
    return int(row["pid"])


def parse_notify_payload(payload: str) -> SessionEventSignal | None:
    try:
        data: Any = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Ignoring malformed session NOTIFY payload")
        return None
    if not isinstance(data, dict) or data.get("type") != "session_events":
        return None
    session_id = data.get("session_id")
    first_seq = _optional_int(data.get("first_seq"))
    last_seq = _optional_int(data.get("last_seq"))
    if not isinstance(session_id, str) or not session_id:
        return None
    if first_seq is _INVALID_INT or last_seq is _INVALID_INT:
        return None
    return SessionEventSignal(
        session_id=session_id,
        first_seq=first_seq,
        last_seq=last_seq,
    )


_INVALID_INT = object()


def _optional_int(value: object) -> int | None | object:
    if value is None:
        return None
    if isinstance(value, bool):
        return _INVALID_INT
    if isinstance(value, int):
        return value
    return _INVALID_INT
