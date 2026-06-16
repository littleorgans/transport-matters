"""Addon lifecycle helpers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import httpx
import uvicorn

from transport_matters import breakpoint as bp
from transport_matters.config import get_settings
from transport_matters.counting import TokenCounter, set_counter, set_recent_auth
from transport_matters.index.adapters import get_adapter
from transport_matters.index.adapters.base import RunContext
from transport_matters.index.commit_dispatcher import ShardedCommitDispatcher
from transport_matters.index.tailer import TranscriptTailer, register_session_cursor
from transport_matters.main import create_app
from transport_matters.session.ingest import EventWrite, build_event, build_event_batch
from transport_matters.session.models import SessionPurpose
from transport_matters.session.pool import create_async_pool
from transport_matters.session.writer import SessionWriter
from transport_matters.shared_proxy import ProxyRunBinding
from transport_matters.storage import init_storage
from transport_matters.storage.transcript_snapshot import make_transcript_snapshot_writer
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future
    from pathlib import Path

    from transport_matters.config import Settings
    from transport_matters.index.adapters.base import SessionBinding
    from transport_matters.storage.base import StorageBackend

logger = logging.getLogger(__name__)

# Wire provider → harness cli, for read-back transcript cursor registration (§9.2).
_PROVIDER_CLI = {"anthropic": "claude", "codex": "codex"}
_DIRECT_MINT_PROVIDERS = frozenset({"anthropic"})
_SESSION_POOL_AUX_CONNECTION_RESERVE = 1


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


def build_proxy_run_binding(settings: Settings, storage: StorageBackend) -> ProxyRunBinding:
    """Build the per-run proxy identity from launch settings."""

    return ProxyRunBinding(
        run_id=settings.run_id,
        cli=settings.cli,
        working_dir=settings.cwd,
        storage=storage,
        listen_port=settings.proxy_port,
        upstream=settings.upstream_url,
        agent_home_dir=settings.agent_home_dir,
        owned_native_session_id=settings.owned_native_session_id,
        owned_source_descriptor=settings.owned_source_descriptor,
        launch_fields=MappingProxyType(dict(settings.launch_fields)),
        default_client_passthrough=tuple(settings.default_client_passthrough),
        breakpoint_skip_models=tuple(settings.breakpoint_skip_models),
    )


def _launch_run_context(binding: ProxyRunBinding, started_at: str) -> RunContext | None:
    """Build the owned transcript registration context from launch settings, if complete."""
    if binding.run_id is None or binding.working_dir is None or binding.cli is None:
        return None
    if binding.owned_native_session_id is None:
        return None
    workspace = workspace_id(binding.working_dir)
    return RunContext(
        run_id=binding.run_id,
        cwd=str(binding.working_dir),
        workspace_slug=workspace.slug,
        workspace_hash=workspace.hash,
        cli=binding.cli,
        started_at=started_at,
        native_session_id=binding.owned_native_session_id,
        home_dir=str(binding.agent_home_dir) if binding.agent_home_dir is not None else None,
    )


async def _register_owned_cursor(
    tailer: TranscriptTailer, binding: ProxyRunBinding, started_at: str
) -> None:
    """Register the launcher-owned transcript cursor without the retired exchange sink."""
    try:
        run = _launch_run_context(binding, started_at)
        if run is None:
            return
        adapter = get_adapter(run.cli)
        session_binding = await adapter.bind(run)
        session_binding = session_binding.model_copy(
            update={
                **binding.launch_fields,
                "minted": adapter.provider in _DIRECT_MINT_PROVIDERS,
                "source_descriptor": binding.owned_source_descriptor,
            }
        )
        await register_session_cursor(tailer, adapter, session_binding)
    except Exception:
        logger.exception("owned transcript cursor registration failed")


def _session_purpose_for_binding(binding: SessionBinding) -> SessionPurpose:
    value = getattr(binding, "session_purpose", None)
    if value is None:
        return SessionPurpose.USER
    try:
        return SessionPurpose(value)
    except ValueError:
        logger.warning(
            "ignoring invalid session_purpose launch field session=%s value=%r",
            binding.session_id,
            value,
        )
        return SessionPurpose.USER


@dataclass(slots=True)
class CaptureRuntime:
    http_client: httpx.AsyncClient
    token_counter: TokenCounter
    binding: ProxyRunBinding | None = None
    session_writer: SessionWriter | None = None
    index_tailer: TranscriptTailer | None = None
    commit_dispatcher: ShardedCommitDispatcher | None = None


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

    @property
    def binding(self) -> ProxyRunBinding | None:
        return self.capture.binding


def load_capture_runtime(settings: Settings | None = None) -> CaptureRuntime:
    settings = settings or get_settings()
    storage = init_storage(root=settings.storage_dir)
    binding = build_proxy_run_binding(settings, storage)
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
    commit_dispatcher: ShardedCommitDispatcher | None = None
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
        quarantined_records = 0
        shard_count = settings.session_pool_max_size - _SESSION_POOL_AUX_CONNECTION_RESERVE
        commit_dispatcher = ShardedCommitDispatcher(
            loop=loop,
            submit=writer.submit,
            shard_count=shard_count,
            queue_size=shard_count,
        )

        def submit_events(binding: SessionBinding, events: list[EventWrite]) -> Future[Any]:
            nonlocal quarantined_records
            future = commit_dispatcher.submit(
                build_event_batch(
                    binding,
                    events,
                    session_purpose=_session_purpose_for_binding(binding),
                )
            )
            future.add_done_callback(lambda done: log_commit_result(binding, done))
            return future

        def quarantine_window(
            binding: SessionBinding,
            source_path: str,
            byte_start: int,
            byte_end: int,
            raw_excerpt: bytes,
            exc: BaseException,
            attempts: int,
        ) -> Future[Any]:
            return asyncio.run_coroutine_threadsafe(
                writer.quarantine_window(
                    binding,
                    source_path,
                    byte_start,
                    byte_end,
                    raw_excerpt,
                    exc,
                    attempts,
                ),
                loop,
            )

        def log_commit_result(binding: SessionBinding, future: Future[Any]) -> None:
            nonlocal quarantined_records
            if future.cancelled():
                return
            try:
                result = future.result()
            except Exception:
                return
            if not result.ok:
                return
            if not result.quarantined:
                return
            quarantined_records += result.quarantined
            for sqlstate in result.quarantine_sqlstates:
                logger.warning(
                    "quarantined transcript record run=%s session=%s sqlstate=%s total=%d",
                    binding.run_id,
                    binding.session_id,
                    sqlstate,
                    quarantined_records,
                )

        index_tailer = TranscriptTailer(
            build_record=build_event,
            submit_batch=submit_events,
            quarantine_window=quarantine_window,
            snapshot=snapshot_writer,
        )
        index_tailer.start()
        loop.create_task(
            _register_owned_cursor(index_tailer, binding, started_at),
            name="register-owned-transcript-cursor",
        )
    except Exception:
        logger.exception("session capture failed to start; transcript capture disabled this run")
        session_writer = index_tailer = None

    return CaptureRuntime(
        http_client=http_client,
        token_counter=token_counter,
        binding=binding,
        session_writer=session_writer,
        index_tailer=index_tailer,
        commit_dispatcher=commit_dispatcher,
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
    dispatcher = runtime.commit_dispatcher
    if dispatcher is not None:
        await dispatcher.aclose()
    writer = runtime.session_writer
    if writer is not None:
        await writer.aclose()
    # Drain in-flight pause-count tasks before closing the shared HTTP client
    # they depend on (littleorgans/python storage Rule 4, no orphan tasks).
    from transport_matters.pause_session import drain_pause_count_tasks

    await drain_pause_count_tasks()
    await runtime.http_client.aclose()
    set_counter(None)
    if runtime.binding is not None:
        set_recent_auth(None, binding=runtime.binding)
    else:
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
    await close_web_runtime(runtime.web)
    await close_capture_runtime(runtime.capture)
