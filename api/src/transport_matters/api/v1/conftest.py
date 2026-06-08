"""Shared pytest fixtures for the v1 API test package."""

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters import config
from transport_matters.api.v1.session_test_support import create_test_db
from transport_matters.main import create_app
from transport_matters.storage import init_storage, reset_storage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path

    from transport_matters.session.testing import TestDb


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
    from transport_matters import counting
    from transport_matters.api.v1 import exchanges

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


@pytest.fixture
def test_db() -> Generator[TestDb]:
    yield from create_test_db()
