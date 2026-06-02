"""Addon lifecycle helpers."""

import asyncio
import contextlib
import logging
from dataclasses import dataclass

import httpx
import uvicorn

from transport_matters import breakpoint as bp
from transport_matters.config import get_settings
from transport_matters.counting import TokenCounter, set_counter, set_recent_auth
from transport_matters.main import create_app
from transport_matters.storage import init_storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AddonRuntime:
    http_client: httpx.AsyncClient
    token_counter: TokenCounter
    server: uvicorn.Server
    serve_task: asyncio.Task[None]


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
    )


async def close_runtime(runtime: AddonRuntime | None) -> None:
    await bp.clear_all()
    if runtime is None:
        return
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
