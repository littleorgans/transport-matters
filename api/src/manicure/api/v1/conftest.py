"""Shared pytest fixtures for the v1 API test package."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from manicure import config
from manicure.main import create_app
from manicure.storage import init_storage, reset_storage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _setup_storage(tmp_path: Path) -> Generator[None]:
    """Initialise storage with a temp dir before each test."""
    reset_storage()
    init_storage(root=tmp_path)
    yield
    reset_storage()


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Generator[None]:
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_counting_state() -> Generator[None]:
    """Reset process wide counter and auth cache between tests."""
    from manicure import counting
    from manicure.api.v1 import exchanges

    counting.set_counter(None)
    counting.set_recent_auth(None)
    exchanges._compute_locks.clear()
    yield
    counting.set_counter(None)
    counting.set_recent_auth(None)
    exchanges._compute_locks.clear()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
