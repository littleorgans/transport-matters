"""Capture write path regressions with the web runtime off."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from transport_matters.exchange_recorder import persist_exchange
from transport_matters.index.conftest import make_binding
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from transport_matters.session.dao import AsyncSessionDao
from transport_matters.session.ingest import EventWrite, build_event_batch
from transport_matters.session.listen import (
    SessionEventHub,
    SessionEventListener,
    SessionEventSignal,
)
from transport_matters.session.pool import async_connect, create_async_pool
from transport_matters.session.test_foundation import event
from transport_matters.session.writer import SessionWriter
from transport_matters.storage.base import ExchangeArtifacts, IndexEntry, ReqStats
from transport_matters.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from pathlib import Path

    from transport_matters.session.testing import TestDb


def _request_ir() -> InternalRequest:
    return InternalRequest(
        model="claude-3",
        provider="anthropic",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


async def test_exchange_and_session_capture_work_with_web_runtime_off(
    tmp_path: Path,
    test_db: TestDb,
) -> None:
    storage = DiskStorageBackend(tmp_path / "tier1")
    request_ir = _request_ir()
    exchange_id = "exchange-web-off"
    entry = IndexEntry(
        id=exchange_id,
        run_id="run-web-off",
        ts=datetime.now(UTC),
        provider="anthropic",
        model="claude-3",
        path="/v1/messages",
        req=ReqStats(messages_count=1, messages_chars=5, total_chars=5),
    )
    artifacts = ExchangeArtifacts(
        request_raw=b'{"messages":[{"role":"user","content":"hello"}]}',
        request_ir=request_ir,
    )

    assert await persist_exchange(storage, entry, artifacts) is True
    stored = await storage.read_exchange(exchange_id)
    assert stored.request_raw == artifacts.request_raw
    assert stored.request_ir == request_ir

    hub = SessionEventHub()
    subscription = hub.subscribe("session-web-off")
    listener = SessionEventListener(
        test_db.database_url,
        hub,
        channel="tm_test_capture_web_off",
        notify_timeout_s=0.05,
    )
    loop = asyncio.get_running_loop()
    writer = SessionWriter(
        create_async_pool(test_db.database_url, min_size=1, max_size=1),
        loop=loop,
        notify_channel="tm_test_capture_web_off",
    )
    try:
        await listener.start()
        catch_up = await asyncio.wait_for(subscription.queue.get(), timeout=2.0)
        assert catch_up == SessionEventSignal(session_id="session-web-off")

        batch = build_event_batch(
            make_binding("session-web-off"),
            [EventWrite(event=event(0, session_id="session-web-off"))],
        )
        result = await loop.run_in_executor(None, writer.submit_blocking, batch)
        assert (result.ok, result.committed, result.last_seq) == (True, 1, 0)

        signal = await asyncio.wait_for(subscription.queue.get(), timeout=2.0)
        assert signal == SessionEventSignal(session_id="session-web-off", first_seq=0, last_seq=0)

        async with await async_connect(test_db.database_url, autocommit=True) as conn:
            dao = AsyncSessionDao(conn)
            rows = await dao.get_events("session-web-off")
        assert [row.seq for row in rows] == [0]
    finally:
        subscription.close()
        await writer.aclose()
        await listener.aclose()
