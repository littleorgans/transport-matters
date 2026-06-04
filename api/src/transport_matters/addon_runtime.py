"""Addon lifecycle helpers."""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import uvicorn

from transport_matters import breakpoint as bp
from transport_matters.config import get_settings
from transport_matters.counting import TokenCounter, set_counter, set_recent_auth
from transport_matters.index.db import index_db_path
from transport_matters.index.ingest import build_run_facts, make_index_sink
from transport_matters.index.writer import IndexWriter
from transport_matters.main import create_app
from transport_matters.storage import init_storage
from transport_matters.storage.exchange_sink import clear_exchange_sink, set_exchange_sink

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AddonRuntime:
    http_client: httpx.AsyncClient
    token_counter: TokenCounter
    server: uvicorn.Server
    serve_task: asyncio.Task[None]
    index_writer: IndexWriter | None = None


def load_runtime() -> AddonRuntime:
    settings = get_settings()
    storage = init_storage(root=settings.storage_dir)
    from transport_matters.storage.disk import DiskStorageBackend

    if isinstance(storage, DiskStorageBackend):
        logger.info("Storage root: %s", storage.root)

    http_client = httpx.AsyncClient(
        base_url="https://api.anthropic.com",
        timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0),
        trust_env=False,
    )
    token_counter = TokenCounter(http_client)
    set_counter(token_counter)

    # Tier-2 capture (slice 2): the single-writer actor + the injected post-persist sink that
    # closes over the per-run static facts (§6.4). Best-effort — a tier-2 startup failure must
    # never stop the proxy (§7.1).
    index_writer: IndexWriter | None = None
    try:
        index_writer = IndexWriter(str(index_db_path()))
        index_writer.start()
        run_facts = build_run_facts(settings.run_id, settings.cwd, datetime.now(UTC).isoformat())
        set_exchange_sink(make_index_sink(index_writer, run_facts))
    except Exception:
        logger.exception("tier-2 index writer failed to start; wire capture disabled this run")
        index_writer = None

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
    )


async def close_runtime(runtime: AddonRuntime | None) -> None:
    await bp.clear_all()
    if runtime is None:
        return
    # Tier-2 (slice 2): unregister the sink, then drain + checkpoint + close the writer off the
    # event loop (stop() joins the writer thread, so run it in an executor).
    clear_exchange_sink()
    writer = runtime.index_writer
    if writer is not None:
        await asyncio.get_running_loop().run_in_executor(None, lambda: writer.stop(drain=True))
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
