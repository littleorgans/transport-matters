"""Tests for close_runtime teardown logic and the read-back cursor registrar."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import httpx
import pytest
import uvicorn

from transport_matters import addon_runtime, pause_session
from transport_matters import breakpoint as bp
from transport_matters.addon_runtime import (
    AddonRuntime,
    CaptureRuntime,
    WebRuntime,
    close_capture_runtime,
    close_runtime,
    close_web_runtime,
    load_capture_runtime,
    start_web_runtime,
)
from transport_matters.config import Settings
from transport_matters.counting import TokenCounter, get_counter, set_counter, set_recent_auth
from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
    encode_source_descriptor,
)
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.tailer import TranscriptTailer
from transport_matters.main import create_app

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server() -> uvicorn.Server:
    """Build an unstarted uvicorn.Server backed by the real FastAPI app."""
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=0, log_config=None)
    return uvicorn.Server(config)


def _make_runtime(
    *, client: httpx.AsyncClient, counter: TokenCounter, server: uvicorn.Server
) -> tuple[AddonRuntime, asyncio.Task[None]]:
    serve_task: asyncio.Task[None] = asyncio.create_task(
        _serve_until_exit(server), name="web-ui-serve"
    )
    return (
        AddonRuntime(
            capture=CaptureRuntime(http_client=client, token_counter=counter),
            web=WebRuntime(server=server, serve_task=serve_task),
        ),
        serve_task,
    )


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
# close_runtime(None), bp.clear_all only
# ---------------------------------------------------------------------------


async def test_load_capture_runtime_starts_capture_resources_without_uvicorn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capture startup creates counter, writer, tailer, and never instantiates uvicorn.Server."""
    pool = object()

    class ServerShouldNotExist:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("load_capture_runtime must not create uvicorn.Server")

    class FakeWriter:
        def __init__(self, seen_pool: object, *, loop: asyncio.AbstractEventLoop) -> None:
            self.pool = seen_pool
            self.loop = loop
            self.closed = False
            writers.append(self)

        def submit_blocking(self, _batch: object) -> object:
            return type("CommitResult", (), {"ok": True})()

        async def aclose(self) -> None:
            self.closed = True

    class FakeTailer:
        def __init__(self, **_kwargs: object) -> None:
            self.started = False
            self.stopped_with_drain: bool | None = None
            tailers.append(self)

        def start(self) -> None:
            self.started = True

        def stop(self, *, drain: bool) -> None:
            self.stopped_with_drain = drain

    writers: list[FakeWriter] = []
    tailers: list[FakeTailer] = []

    monkeypatch.setattr(uvicorn, "Server", ServerShouldNotExist)
    monkeypatch.setattr(addon_runtime, "init_storage", lambda *, root: object())
    monkeypatch.setattr(addon_runtime, "create_async_pool", lambda: pool)
    monkeypatch.setattr(addon_runtime, "SessionWriter", FakeWriter)
    monkeypatch.setattr(addon_runtime, "TranscriptTailer", FakeTailer)

    runtime = load_capture_runtime(Settings(storage_dir=tmp_path, web_runtime="external"))
    try:
        assert isinstance(runtime.token_counter, TokenCounter)
        assert get_counter() is runtime.token_counter
        assert len(writers) == 1
        assert id(runtime.session_writer) == id(writers[0])
        assert len(tailers) == 1
        assert id(runtime.index_tailer) == id(tailers[0])
        assert tailers[0].started is True
    finally:
        await close_capture_runtime(runtime)

    assert writers[0].closed is True
    assert tailers[0].stopped_with_drain is True


async def test_start_and_close_web_runtime_use_requested_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Web startup remains explicit and close_web_runtime owns only the serve task."""

    class FakeServer:
        def __init__(self, config: uvicorn.Config) -> None:
            self.config = config
            self._should_exit = False
            self._exit_event = asyncio.Event()

        @property
        def should_exit(self) -> bool:
            return self._should_exit

        @should_exit.setter
        def should_exit(self, value: bool) -> None:
            self._should_exit = value
            if value:
                self._exit_event.set()

        async def serve(self) -> None:
            await self._exit_event.wait()

    monkeypatch.setattr(uvicorn, "Server", FakeServer)

    runtime = start_web_runtime(Settings(web_port=9242))
    assert runtime.server.config.port == 9242

    await close_web_runtime(runtime)
    assert runtime.server.should_exit is True
    assert runtime.serve_task.done()


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
    client = httpx.AsyncClient()
    counter = TokenCounter(client)
    set_counter(counter)
    runtime, serve_task = _make_runtime(client=client, counter=counter, server=server)

    await close_runtime(runtime)

    assert server.should_exit is True
    assert serve_task.done()
    assert not serve_task.cancelled()
    assert client.is_closed


async def test_close_runtime_closes_web_before_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedded web shuts down before capture resources are torn down."""
    order: list[str] = []

    async def fake_close_web(_runtime: WebRuntime | None) -> None:
        order.append("web")

    async def fake_close_capture(_runtime: CaptureRuntime | None) -> None:
        order.append("capture")

    monkeypatch.setattr(addon_runtime, "close_web_runtime", fake_close_web)
    monkeypatch.setattr(addon_runtime, "close_capture_runtime", fake_close_capture)
    runtime = AddonRuntime(
        capture=cast("CaptureRuntime", object()),
        web=cast("WebRuntime", object()),
    )

    await close_runtime(runtime)

    assert order == ["web", "capture"]


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
    client = httpx.AsyncClient()

    original_aclose = client.aclose

    async def tracked_aclose() -> None:
        order.append("aclose")
        await original_aclose()

    monkeypatch.setattr(client, "aclose", tracked_aclose)

    counter = TokenCounter(client)
    set_counter(counter)

    runtime = AddonRuntime(
        capture=CaptureRuntime(http_client=client, token_counter=counter),
        web=None,
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
        capture=CaptureRuntime(http_client=client, token_counter=counter),
        web=WebRuntime(server=server, serve_task=serve_task),
    )

    await close_runtime(runtime)

    # Give the event loop a tick so cancellation propagates.
    await asyncio.sleep(0)

    assert serve_task.cancelled()
    assert client.is_closed


def _codex_binding() -> SessionBinding:
    return SessionBinding(
        session_id="sess-codex",
        provider="codex",
        run_id="run1",
        cwd="/w",
        workspace_slug="s",
        workspace_hash="h",
        started_at="t",
        cli="codex",
        native_session_id="019e0000-0000-7000-8000-00000000c0de",
        minted=False,
    )


async def test_cursor_registrar_registers_codex_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """A codex wire binding (read-back) must resolve to the codex adapter and schedule its cursor.

    The registrar maps wire provider → cli via _PROVIDER_CLI; codex was claude-only before slice 5,
    so a codex binding silently no-op'd (no transcript tail), this guards the codex mapping.
    """
    calls: list[tuple[str, str]] = []

    async def fake_register(
        tailer: TranscriptTailer, adapter: object, binding: SessionBinding
    ) -> None:
        calls.append((getattr(adapter, "cli", "?"), binding.session_id))

    monkeypatch.setattr(addon_runtime, "register_session_cursor", fake_register)
    registrar = addon_runtime._make_cursor_registrar(TranscriptTailer(), asyncio.get_running_loop())

    registrar(_codex_binding())
    await asyncio.sleep(0.05)  # let the scheduled coroutine run

    assert calls == [("codex", "sess-codex")]


async def test_close_runtime_clears_counter_and_auth() -> None:
    """set_counter(None) and set_recent_auth(None) are called on close."""
    from transport_matters.counting import _counter, _recent_auth

    client = httpx.AsyncClient()
    counter = TokenCounter(client)
    set_counter(counter)
    runtime = AddonRuntime(
        capture=CaptureRuntime(http_client=client, token_counter=counter),
        web=None,
    )

    await close_runtime(runtime)

    assert _counter is None
    assert _recent_auth is None


async def test_register_owned_cursor_uses_launch_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = "019e0000-0000-7000-8000-00000000c0de"
    descriptor = encode_source_descriptor(
        FileTailSource(path=str(tmp_path / "rollout.jsonl"), format="codex_rollout")
    )
    settings = Settings(
        run_id="run1",
        cwd=tmp_path / "workspace",
        cli="codex",
        owned_native_session_id=native,
        owned_source_descriptor=descriptor,
        agent_home_dir=tmp_path / "home",
    )
    calls: list[tuple[str, SessionBinding]] = []

    async def fake_register(
        tailer: TranscriptTailer, adapter: object, binding: SessionBinding
    ) -> None:
        calls.append((getattr(adapter, "cli", "?"), binding))

    monkeypatch.setattr(addon_runtime, "register_session_cursor", fake_register)

    await addon_runtime._register_owned_cursor(
        TranscriptTailer(), settings, "2026-06-06T00:00:00+00:00"
    )

    assert len(calls) == 1
    cli, binding = calls[0]
    assert cli == "codex"
    assert binding.session_id == synth_session_id("run1", "codex", native)
    assert binding.source_descriptor == descriptor
    assert binding.home_dir == str(tmp_path / "home")
