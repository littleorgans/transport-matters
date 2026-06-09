"""Addon lifecycle helpers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import uvicorn

from transport_matters import breakpoint as bp
from transport_matters.config import get_settings
from transport_matters.counting import TokenCounter, set_counter, set_recent_auth
from transport_matters.index.adapters import get_adapter
from transport_matters.index.adapters.base import RunContext
from transport_matters.index.tailer import TranscriptTailer, register_session_cursor
from transport_matters.main import create_app
from transport_matters.session.ingest import EventWrite, build_event, build_event_batch
from transport_matters.session.pool import create_async_pool
from transport_matters.session.writer import SessionWriter
from transport_matters.storage import init_storage
from transport_matters.storage.transcript_snapshot import make_transcript_snapshot_writer
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from transport_matters.config import Settings
    from transport_matters.index.adapters.base import SessionBinding

logger = logging.getLogger(__name__)

# Wire provider → harness cli, for read-back transcript cursor registration (§9.2).
_PROVIDER_CLI = {"anthropic": "claude", "codex": "codex"}
_DIRECT_MINT_PROVIDERS = frozenset({"anthropic"})


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """The running event loop, or None when load_runtime is called outside one (degraded push)."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _make_cursor_registrar(
    tailer: TranscriptTailer, loop: asyncio.AbstractEventLoop | None
) -> Callable[[SessionBinding], None]:
    """Build the on_binding callback: schedule a read-back transcript cursor for a wire binding."""

    def register(binding: SessionBinding) -> None:
        cli = _PROVIDER_CLI.get(binding.provider)
        if cli is None or loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            register_session_cursor(tailer, get_adapter(cli), binding), loop
        )

    return register


def _launch_run_context(settings: Settings, started_at: str) -> RunContext | None:
    """Build the owned transcript registration context from launch settings, if complete."""
    if settings.run_id is None or settings.cwd is None or settings.cli is None:
        return None
    if settings.owned_native_session_id is None:
        return None
    workspace = workspace_id(settings.cwd)
    return RunContext(
        run_id=settings.run_id,
        cwd=str(settings.cwd),
        workspace_slug=workspace.slug,
        workspace_hash=workspace.hash,
        cli=settings.cli,
        started_at=started_at,
        native_session_id=settings.owned_native_session_id,
        home_dir=str(settings.agent_home_dir) if settings.agent_home_dir is not None else None,
    )


async def _register_owned_cursor(
    tailer: TranscriptTailer, settings: Settings, started_at: str
) -> None:
    """Register the launcher-owned transcript cursor without the retired exchange sink."""
    try:
        run = _launch_run_context(settings, started_at)
        if run is None:
            return
        adapter = get_adapter(run.cli)
        binding = await adapter.bind(run)
        binding = binding.model_copy(
            update={
                "minted": adapter.provider in _DIRECT_MINT_PROVIDERS,
                "source_descriptor": settings.owned_source_descriptor,
            }
        )
        await register_session_cursor(tailer, adapter, binding)
    except Exception:
        logger.exception("owned transcript cursor registration failed")


@dataclass(slots=True)
class CaptureRuntime:
    http_client: httpx.AsyncClient
    token_counter: TokenCounter
    session_writer: SessionWriter | None = None
    index_tailer: TranscriptTailer | None = None


@dataclass(slots=True)
class WebRuntime:
    server: uvicorn.Server
    serve_task: asyncio.Task[None]


@dataclass(slots=True)
class AddonRuntime:
    capture: CaptureRuntime
    web: WebRuntime | None

    @property
    def http_client(self) -> httpx.AsyncClient:
        return self.capture.http_client

    @property
    def token_counter(self) -> TokenCounter:
        return self.capture.token_counter

    @property
    def session_writer(self) -> SessionWriter | None:
        return self.capture.session_writer

    @property
    def index_tailer(self) -> TranscriptTailer | None:
        return self.capture.index_tailer


def load_capture_runtime(settings: Settings | None = None) -> CaptureRuntime:
    settings = settings or get_settings()
    storage = init_storage(root=settings.storage_dir)
    from transport_matters.storage.disk import DiskStorageBackend

    # The tier-1 storage root is workspace-scoped. The snapshot writer must use the backend's real
    # root so copied transcript bytes land beside the live run artifacts.
    storage_root: Path | None = None
    if isinstance(storage, DiskStorageBackend):
        storage_root = storage.root
        logger.info("Storage root: %s", storage.root)

    http_client = httpx.AsyncClient(
        base_url="https://api.anthropic.com",
        timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0),
        trust_env=False,
    )
    token_counter = TokenCounter(http_client)
    set_counter(token_counter)

    # Session capture: the Postgres writer, transcript tailer, and tier-1 transcript snapshot.
    # Best-effort startup failure must never stop the proxy (§7.1).
    loop = _running_loop()
    session_writer: SessionWriter | None = None
    index_tailer: TranscriptTailer | None = None
    try:
        if loop is None:
            raise RuntimeError("server loop is unavailable for session writer")
        started_at = datetime.now(UTC).isoformat()
        writer = SessionWriter(create_async_pool(), loop=loop)
        session_writer = writer
        # Tier-1 transcript snapshot (§7.1/§11, slice 8b-i): tee consumed transcript bytes into the
        # run dir so tier-1 owns the transcript even if the CLI GCs its own file. Built here closing
        # over the workspace-scoped storage_root (same root the wire artifacts use), injected into
        # the tailer as a plain callable, the index-layer tailer never imports a storage write API
        # (DAG). None when there is no disk backend (the snapshot has nowhere durable to land).
        snapshot_writer = (
            make_transcript_snapshot_writer(storage_root) if storage_root is not None else None
        )

        def submit_events(binding: SessionBinding, events: list[EventWrite]) -> None:
            result = writer.submit_blocking(build_event_batch(binding, events))
            if not result.ok:
                raise RuntimeError("session writer commit failed")

        index_tailer = TranscriptTailer(
            build_record=build_event,
            submit_batch=submit_events,
            snapshot=snapshot_writer,
        )
        index_tailer.start()
        loop.create_task(
            _register_owned_cursor(index_tailer, settings, started_at),
            name="register-owned-transcript-cursor",
        )
    except Exception:
        logger.exception("session capture failed to start; transcript capture disabled this run")
        session_writer = index_tailer = None

    return CaptureRuntime(
        http_client=http_client,
        token_counter=token_counter,
        session_writer=session_writer,
        index_tailer=index_tailer,
    )


def start_web_runtime(settings: Settings) -> WebRuntime:
    app = create_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=settings.web_port,
        log_config=None,
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve(), name="web-ui-serve")
    logger.info("Web UI: http://127.0.0.1:%d", settings.web_port)
    return WebRuntime(server=server, serve_task=serve_task)


def load_runtime() -> AddonRuntime:
    settings = get_settings()
    capture = load_capture_runtime(settings)
    web = start_web_runtime(settings) if settings.web_runtime == "embedded" else None
    return AddonRuntime(capture=capture, web=web)


async def close_capture_runtime(runtime: CaptureRuntime | None) -> None:
    await bp.clear_all()
    if runtime is None:
        return
    # Stop the tailer FIRST. Its final drain submits any last events before the writer closes.
    loop = asyncio.get_running_loop()
    tailer = runtime.index_tailer
    if tailer is not None:
        await loop.run_in_executor(None, lambda: tailer.stop(drain=True))
    writer = runtime.session_writer
    if writer is not None:
        await writer.aclose()
    # Drain in-flight pause-count tasks before closing the shared HTTP client
    # they depend on (littleorgans/python storage Rule 4, no orphan tasks).
    from transport_matters.pause_session import drain_pause_count_tasks

    await drain_pause_count_tasks()
    await runtime.http_client.aclose()
    set_counter(None)
    set_recent_auth(None)


async def close_web_runtime(runtime: WebRuntime | None) -> None:
    if runtime is None:
        return
    runtime.server.should_exit = True
    try:
        await asyncio.wait_for(runtime.serve_task, timeout=5.0)
    except TimeoutError:
        runtime.serve_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runtime.serve_task


async def close_runtime(runtime: AddonRuntime | None) -> None:
    if runtime is None:
        await close_capture_runtime(None)
        return
    await close_capture_runtime(runtime.capture)
    await close_web_runtime(runtime.web)
