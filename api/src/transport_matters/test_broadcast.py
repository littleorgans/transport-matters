"""Tests for the SSE broadcaster."""

import json
import logging

import pytest

from transport_matters import broadcast


class TestBroadcast:
    def setup_method(self) -> None:
        broadcast._subscribers.clear()
        broadcast._next_id = 0

    def test_subscribe_receive(self) -> None:
        q = broadcast.subscribe()
        broadcast.emit({"type": "test", "value": 1})
        assert not q.empty()
        data = q.get_nowait()
        parsed = json.loads(data)
        assert parsed["type"] == "test"

    def test_unsubscribe(self) -> None:
        q = broadcast.subscribe()
        broadcast.unsubscribe(q)
        broadcast.emit({"type": "test"})
        assert q.empty()

    def test_multiple_subscribers(self) -> None:
        q1 = broadcast.subscribe()
        q2 = broadcast.subscribe()
        broadcast.emit({"type": "multi"})
        assert not q1.empty()
        assert not q2.empty()
        d1 = q1.get_nowait()
        d2 = q2.get_nowait()
        assert d1 == d2
        parsed = json.loads(d1)
        assert parsed["type"] == "multi"

    def test_bounded_queue_maxsize(self) -> None:
        q = broadcast.subscribe()
        assert q.maxsize == broadcast.QUEUE_MAX_SIZE

    def test_overflow_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        q = broadcast.subscribe()
        for i in range(broadcast.QUEUE_MAX_SIZE):
            q.put_nowait(f'{{"i": {i}}}')
        assert q.full()

        with caplog.at_level(logging.WARNING, logger="transport_matters.broadcast"):
            broadcast.emit({"type": "overflow"})

        assert q.qsize() == broadcast.QUEUE_MAX_SIZE
        assert any("Dropped SSE event" in r.message for r in caplog.records)
