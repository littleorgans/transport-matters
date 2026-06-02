"""Tests for close_runtime teardown logic."""

import asyncio

import httpx
import pytest
import uvicorn

from transport_matters import breakpoint as bp
from transport_matters import pause_session
from transport_matters.addon_runtime import AddonRuntime, close_runtime
from transport_matters.counting import TokenCounter, set_counter, set_recent_auth
from transport_matters.main import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server() -> uvicorn.Server:
    """Build an unstarted uvicorn.Server backed by the real FastAPI app."""
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=0, log_config=None)
    return uvicorn.Server(config)


async def _serve_until_exit(server: uvicorn.Server) -> None:
    """Cooperate with should_exit without actually binding a socket."""
    exit_event: asyncio.Event = asyncio.Event()

    def _poll() -> None:
        if server.should_exit:
            exit_event.set()
        else:
            asyncio.get_event_loop().call_later(0.005, _poll)

    asyncio.get_event_loop().call_later(0.005, _poll)
    await exit_event.wait()


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset module-global state around every test."""
    bp.disarm()
    bp._paused.clear()
    pause_session._pause_count_tasks.clear()
    set_counter(None)
    set_recent_auth(None)


# ---------------------------------------------------------------------------
# close_runtime(None) — bp.clear_all only
# ---------------------------------------------------------------------------


async def test_close_runtime_none_calls_clear_all() -> None:
    """close_runtime(None) runs bp.clear_all without crashing."""
    await close_runtime(None)
    # If we reach here without exception the contract is satisfied.


# ---------------------------------------------------------------------------
# close_runtime with a real-ish AddonRuntime
# ---------------------------------------------------------------------------


async def test_close_runtime_shuts_down_server_and_client() -> None:
    """close_runtime signals exit, awaits the serve task, and closes the client."""
    server = _make_server()
    serve_task: asyncio.Task[None] = asyncio.create_task(
        _serve_until_exit(server), name="web-ui-serve"
    )
    client = httpx.AsyncClient()
    counter = TokenCounter(client)
    set_counter(counter)

    runtime = AddonRuntime(
        http_client=client,
        token_counter=counter,
        server=server,
        serve_task=serve_task,
    )

    await close_runtime(runtime)

    assert server.should_exit is True
    assert serve_task.done()
    assert not serve_task.cancelled()
    assert client.is_closed


async def test_close_runtime_drains_pause_tasks_before_client_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """drain_pause_count_tasks is awaited before http_client.aclose()."""
    monkeypatch.setattr(pause_session, "_PAUSE_DRAIN_TIMEOUT_S", 2.0)

    order: list[str] = []

    drain_done = asyncio.Event()

    async def sentinel_task() -> None:
        await asyncio.sleep(0)  # yield so drain actually awaits us
        order.append("drained")
        drain_done.set()

    task: asyncio.Task[None] = asyncio.create_task(sentinel_task(), name="pause-count:sentinel")
    pause_session._pause_count_tasks.add(task)
    task.add_done_callback(pause_session._retire_pause_count_task)

    # Wrap aclose to record its call order.
    server = _make_server()
    serve_task: asyncio.Task[None] = asyncio.create_task(
        _serve_until_exit(server), name="web-ui-serve"
    )
    client = httpx.AsyncClient()

    original_aclose = client.aclose

    async def tracked_aclose() -> None:
        order.append("aclose")
        await original_aclose()

    monkeypatch.setattr(client, "aclose", tracked_aclose)

    counter = TokenCounter(client)
    set_counter(counter)

    runtime = AddonRuntime(
        http_client=client,
        token_counter=counter,
        server=server,
        serve_task=serve_task,
    )

    await close_runtime(runtime)

    assert "drained" in order
    assert "aclose" in order
    assert order.index("drained") < order.index("aclose"), "drain must complete before aclose"


async def test_close_runtime_cancels_stubborn_serve_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A serve_task that ignores should_exit is cancelled after timeout."""
    server = _make_server()

    # Task that loops forever, ignoring should_exit.
    async def stubborn_serve() -> None:
        never_set: asyncio.Event = asyncio.Event()
        await never_set.wait()

    serve_task: asyncio.Task[None] = asyncio.create_task(
        stubborn_serve(), name="web-ui-serve-stubborn"
    )

    # Patch wait_for on asyncio so only the serve timeout is tiny.
    original_wait_for = asyncio.wait_for

    async def fast_wait_for(coro: object, deadline: float | None = None) -> object:
        # Only shrink the serve_task wait; let others (drain) use full timeout.
        effective = 0.01 if deadline == 5.0 else deadline
        return await original_wait_for(coro, timeout=effective)  # type: ignore[arg-type]

    # asyncio.wait_for signature uses keyword `timeout`; adapt the monkeypatch.
    async def patched_wait_for(coro: object, timeout: float | None = None) -> object:  # noqa: ASYNC109
        return await fast_wait_for(coro, deadline=timeout)

    monkeypatch.setattr(asyncio, "wait_for", patched_wait_for)

    client = httpx.AsyncClient()
    counter = TokenCounter(client)
    set_counter(counter)

    runtime = AddonRuntime(
        http_client=client,
        token_counter=counter,
        server=server,
        serve_task=serve_task,
    )

    await close_runtime(runtime)

    # Give the event loop a tick so cancellation propagates.
    await asyncio.sleep(0)

    assert serve_task.cancelled()
    assert client.is_closed


async def test_close_runtime_clears_counter_and_auth() -> None:
    """set_counter(None) and set_recent_auth(None) are called on close."""
    from transport_matters.counting import _counter, _recent_auth

    server = _make_server()
    serve_task: asyncio.Task[None] = asyncio.create_task(
        _serve_until_exit(server), name="web-ui-serve"
    )
    client = httpx.AsyncClient()
    counter = TokenCounter(client)
    set_counter(counter)

    runtime = AddonRuntime(
        http_client=client,
        token_counter=counter,
        server=server,
        serve_task=serve_task,
    )

    await close_runtime(runtime)

    assert _counter is None
    assert _recent_auth is None
