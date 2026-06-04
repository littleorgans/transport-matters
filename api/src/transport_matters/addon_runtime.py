"""Addon lifecycle helpers."""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import uvicorn

from transport_matters import breakpoint as bp
from transport_matters import broadcast
from transport_matters.config import get_settings
from transport_matters.counting import TokenCounter, set_counter, set_recent_auth
from transport_matters.index.adapters import get_adapter
from transport_matters.index.db import index_db_path
from transport_matters.index.ingest import build_run_facts, make_index_sink
from transport_matters.index.tailer import TranscriptTailer, register_session_cursor
from transport_matters.index.writer import IndexWriter
from transport_matters.main import create_app
from transport_matters.storage import init_storage
from transport_matters.storage.exchange_sink import clear_exchange_sink, set_exchange_sink

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from transport_matters.index.adapters.base import SessionBinding

logger = logging.getLogger(__name__)

# Wire provider → harness cli, for read-back transcript cursor registration (§9.2). claude only
# for now (slice 4b); codex/gemini/opencode join in slices 5/6.
_PROVIDER_CLI = {"anthropic": "claude"}


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


@dataclass(slots=True)
class AddonRuntime:
    http_client: httpx.AsyncClient
    token_counter: TokenCounter
    server: uvicorn.Server
    serve_task: asyncio.Task[None]
    index_writer: IndexWriter | None = None
    index_tailer: TranscriptTailer | None = None


def load_runtime() -> AddonRuntime:
    settings = get_settings()
    storage = init_storage(root=settings.storage_dir)
    from transport_matters.storage.disk import DiskStorageBackend

    # The tier-1 storage root is workspace-scoped (settings.storage_dir) while the tier-2 index.db
    # is global (index_db_path == default root). raw_dir is an absolute tier-1 pointer, so the sink
    # must stamp it with the BACKEND's real root, not the default — else GET /raw 404s on a pointer
    # that dangles off the wrong root (roadtest2 #1).
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

    # Tier-2 capture (slices 2/4): the single-writer actor with post-COMMIT live push (§9.4), the
    # injected post-persist sink (§6.4), and the transcript tailer (§9.2). Best-effort — a tier-2
    # startup failure must never stop the proxy (§7.1).
    loop = _running_loop()
    index_writer: IndexWriter | None = None
    index_tailer: TranscriptTailer | None = None
    try:
        index_writer = IndexWriter(str(index_db_path()), loop=loop, emit=broadcast.emit)
        index_writer.start()
        index_tailer = TranscriptTailer(index_writer.submit)
        index_tailer.start()
        run_facts = build_run_facts(settings.run_id, settings.cwd, datetime.now(UTC).isoformat())
        on_binding = _make_cursor_registrar(index_tailer, loop)
        set_exchange_sink(
            make_index_sink(index_writer, run_facts, on_binding, storage_root=storage_root)
        )
    except Exception:
        logger.exception(
            "tier-2 capture failed to start; wire/transcript capture disabled this run"
        )
        index_writer = index_tailer = None

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
    return AddonRuntime(
        http_client=http_client,
        token_counter=token_counter,
        server=server,
        serve_task=serve_task,
        index_writer=index_writer,
        index_tailer=index_tailer,
    )


async def close_runtime(runtime: AddonRuntime | None) -> None:
    await bp.clear_all()
    if runtime is None:
        return
    # Tier-2 (slices 2/4): unregister the sink, then stop the tailer FIRST (its final drain submits
    # any last turns) and drain + checkpoint + close the writer. Both join background threads, so
    # run them off the event loop.
    clear_exchange_sink()
    loop = asyncio.get_running_loop()
    tailer = runtime.index_tailer
    if tailer is not None:
        await loop.run_in_executor(None, lambda: tailer.stop(drain=True))
    writer = runtime.index_writer
    if writer is not None:
        await loop.run_in_executor(None, lambda: writer.stop(drain=True))
    # Drain in-flight pause-count tasks before closing the shared HTTP client
    # they depend on (littleorgans/python storage Rule 4, no orphan tasks).
    from transport_matters.pause_session import drain_pause_count_tasks

    await drain_pause_count_tasks()
    runtime.server.should_exit = True
    try:
        await asyncio.wait_for(runtime.serve_task, timeout=5.0)
    except TimeoutError:
        runtime.serve_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runtime.serve_task
    await runtime.http_client.aclose()
    set_counter(None)
    set_recent_auth(None)
