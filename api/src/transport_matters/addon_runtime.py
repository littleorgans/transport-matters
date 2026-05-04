"""Addon lifecycle helpers."""

from __future__ import annotations

import asyncio
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
    asyncio.ensure_future(server.serve())
    logger.info("Web UI: http://127.0.0.1:%d", settings.web_port)
    return AddonRuntime(http_client=http_client, token_counter=token_counter)


async def close_runtime(runtime: AddonRuntime | None) -> None:
    await bp.clear_all()
    if runtime is None:
        return
    await runtime.http_client.aclose()
    set_counter(None)
    set_recent_auth(None)
