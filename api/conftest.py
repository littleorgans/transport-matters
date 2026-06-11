import os

# Set test environment before any app imports trigger Settings validation.
os.environ.setdefault("DEBUG", "true")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from transport_matters import env_keys  # noqa: E402
from transport_matters.config import get_settings  # noqa: E402
from transport_matters.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_transport_matters_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Point TRANSPORT_MATTERS_HOME at an isolated dir so tests never read the
    developer's real ~/.transport-matters/settings.toml. Operator config is read
    from HOME (decoupled from per-run STORAGE_DIR), so without this a populated dev
    home would leak DB config into tests that assume an unconfigured store. Tests
    that need specific config override this with their own monkeypatch."""
    monkeypatch.setenv(env_keys.HOME, str(tmp_path_factory.mktemp("tm-home")))


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Ensure each test gets fresh settings (respects per-test env overrides)."""
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _trusted_test_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Extend the Host allowlist with the harness hosts ("testserver" is the
    TestClient default, "test" the AsyncClient base_url host). Injected here so
    the shipped Settings.trusted_hosts default stays loopback-only."""
    monkeypatch.setenv(
        f"{env_keys.ENV_PREFIX}TRUSTED_HOSTS",
        '["localhost", "127.0.0.1", "::1", "testserver", "test"]',
    )


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
