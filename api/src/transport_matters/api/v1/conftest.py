"""Shared pytest fixtures for the v1 API test package."""

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters import config
from transport_matters.api.v1.session_test_support import create_test_db
from transport_matters.launch_manifest import write_workspace_manifest
from transport_matters.main import create_app
from transport_matters.storage import init_storage, reset_storage
from transport_matters.workspace import run_root

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path

    from transport_matters.session.testing import TestDb


@pytest.fixture(autouse=True)
def _setup_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Initialise storage with a temp dir before each test."""
    storage_root = tmp_path / "storage"
    home_root = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(home_root))
    monkeypatch.setenv("TRANSPORT_MATTERS_STORAGE_DIR", str(storage_root))
    config.get_settings.cache_clear()
    reset_storage()
    init_storage(root=storage_root)
    for run_id in ("run-current", "run-old"):
        write_workspace_manifest(
            manifest_path=run_root(workspace, run_id) / "manifest.json",
            working_dir=workspace,
            storage_dir=storage_root,
            run_id=run_id,
            home_dir=None,
            proxy_port=1,
            web_port=None,
        )
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
