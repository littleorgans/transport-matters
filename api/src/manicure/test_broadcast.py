"""Tests for the SSE broadcaster."""

from manicure import broadcast


class TestBroadcast:
    def setup_method(self) -> None:
        # Clear any leftover subscribers between tests
        broadcast._subscribers.clear()

    def test_subscribe_receive(self) -> None:
        q = broadcast.subscribe()
        broadcast.emit({"type": "test", "value": 1})
        assert not q.empty()
        data = q.get_nowait()
        assert '"type": "test"' in data

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
        assert '"type": "multi"' in d1
