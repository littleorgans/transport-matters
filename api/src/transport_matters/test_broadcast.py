import json
import logging

import pytest

from transport_matters import broadcast


class TestBroadcast:
    def setup_method(self) -> None:
        broadcast._subscribers.clear()
        broadcast._next_id = 0

    def test_subscribe_receive(self) -> None:
        q = broadcast.subscribe("run-a")
        broadcast.emit({"type": "test", "value": 1}, run_id="run-a")
        msg = q.get_nowait()
        assert json.loads(msg) == {"type": "test", "value": 1, "run_id": "run-a"}

    def test_unsubscribe(self) -> None:
        q = broadcast.subscribe("run-a")
        broadcast.unsubscribe(q)
        assert not broadcast._subscribers
        broadcast.emit({"type": "test"}, run_id="run-a")

    def test_multiple_subscribers_same_run(self) -> None:
        q1 = broadcast.subscribe("run-a")
        q2 = broadcast.subscribe("run-a")
        broadcast.emit({"type": "multi"}, run_id="run-a")
        assert q1.get_nowait()
        assert q2.get_nowait()

    def test_subscribers_only_receive_their_run(self) -> None:
        run_a = broadcast.subscribe("run-a")
        run_b = broadcast.subscribe("run-b")

        broadcast.emit({"type": "scoped"}, run_id="run-a")

        assert json.loads(run_a.get_nowait()) == {"type": "scoped", "run_id": "run-a"}
        assert run_b.empty()

    def test_subscribe_requires_run_id(self) -> None:
        with pytest.raises(ValueError, match="run_id is required"):
            broadcast.subscribe("")

    def test_emit_requires_run_id(self) -> None:
        with pytest.raises(ValueError, match="run_id is required"):
            broadcast.emit({"type": "missing"}, run_id="")

    def test_bounded_queue_maxsize(self) -> None:
        q = broadcast.subscribe("run-a")
        assert q.maxsize == broadcast.QUEUE_MAX_SIZE

    def test_overflow_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        q = broadcast.subscribe("run-a")
        # Fill queue
        for i in range(broadcast.QUEUE_MAX_SIZE):
            q.put_nowait(str(i))
        with caplog.at_level(logging.WARNING):
            broadcast.emit({"type": "overflow"}, run_id="run-a")
        assert "Dropped SSE event for subscriber" in caplog.text
