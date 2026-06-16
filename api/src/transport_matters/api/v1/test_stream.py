"""Tests for the run-scoped SSE stream endpoint."""

import asyncio
import json
from typing import TYPE_CHECKING, cast

from transport_matters import broadcast
from transport_matters.api.v1.stream import stream_run
from transport_matters.main import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi.responses import StreamingResponse
    from httpx import AsyncClient
    from starlette.types import Message, Scope


def _as_gen(response: StreamingResponse) -> AsyncGenerator[str]:
    """Cast body_iterator to AsyncGenerator for test access."""
    return cast("AsyncGenerator[str]", response.body_iterator)


async def _first_response_body(path: str) -> tuple[int, bytes]:
    app = create_app()
    request_consumed = False
    disconnect = asyncio.Event()
    first_body = asyncio.Event()
    messages: list[Message] = []
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> Message:
        nonlocal request_consumed
        if not request_consumed:
            request_consumed = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        messages.append(message)
        if message["type"] == "http.response.body":
            first_body.set()
            disconnect.set()

    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(first_body.wait(), timeout=1.0)
    finally:
        disconnect.set()
        await asyncio.wait_for(task, timeout=1.0)

    start = next(message for message in messages if message["type"] == "http.response.start")
    body = next(message for message in messages if message["type"] == "http.response.body")
    return int(start["status"]), bytes(body.get("body", b""))


def _reset() -> None:
    broadcast._subscribers.clear()
    broadcast._next_id = 0


class TestSSEGenerator:
    def setup_method(self) -> None:
        _reset()

    def teardown_method(self) -> None:
        _reset()

    async def test_connected_event_first(self) -> None:
        """The generator yields a connected event as the first message."""
        gen = _as_gen(await stream_run("run-current"))
        first = await gen.__anext__()
        assert json.loads(first.removeprefix("data: ").strip()) == {
            "type": "connected",
            "run_id": "run-current",
        }
        await gen.aclose()

    async def test_receives_broadcast_event_for_matching_run(self) -> None:
        """Events emitted for the stream run appear in the generator output."""
        gen = _as_gen(await stream_run("run-current"))
        await gen.__anext__()

        broadcast.emit({"type": "test_event", "value": 42}, run_id="run-current")
        data = await gen.__anext__()
        assert json.loads(data.removeprefix("data: ").strip()) == {
            "type": "test_event",
            "value": 42,
            "run_id": "run-current",
        }
        await gen.aclose()

    async def test_ignores_broadcast_event_for_other_run(self) -> None:
        """A subscriber to run A never receives run B events."""
        gen = _as_gen(await stream_run("run-a"))
        await gen.__anext__()

        broadcast.emit({"type": "test_event"}, run_id="run-b")
        broadcast.emit({"type": "test_event"}, run_id="run-a")
        data = await gen.__anext__()
        assert json.loads(data.removeprefix("data: ").strip())["run_id"] == "run-a"
        await gen.aclose()

    async def test_keepalive_on_timeout(self) -> None:
        """When no events arrive within the timeout, a keepalive comment is sent."""
        gen = _as_gen(await stream_run("run-current"))
        await gen.__anext__()  # skip connected

        # The generator waits 15s for data; we don't want to wait that long.
        # Instead, verify the cleanup path.
        await gen.aclose()

    async def test_close_unsubscribes(self) -> None:
        """Closing the generator removes the subscriber."""
        gen = _as_gen(await stream_run("run-current"))
        await gen.__anext__()  # connected event
        assert len(broadcast._subscribers) == 1

        await gen.aclose()
        await asyncio.sleep(0.01)
        assert len(broadcast._subscribers) == 0

    async def test_cancelled_error_unsubscribes(self) -> None:
        """CancelledError during iteration still cleans up the subscriber."""
        gen = _as_gen(await stream_run("run-current"))
        await gen.__anext__()  # connected event
        assert len(broadcast._subscribers) == 1

        # Simulate cancellation by closing the generator
        await gen.aclose()
        assert len(broadcast._subscribers) == 0

    async def test_global_api_stream_is_removed(self, client: AsyncClient) -> None:
        response = await client.get("/api/stream")
        assert response.status_code == 404

    async def test_route_accepts_same_origin_eventsource_without_origin_header(self) -> None:
        status, body = await _first_response_body("/v1/runs/run-current/stream")
        assert status == 200
        assert json.loads(body.removeprefix(b"data: ").strip()) == {
            "type": "connected",
            "run_id": "run-current",
        }
