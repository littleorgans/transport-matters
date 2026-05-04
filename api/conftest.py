import os

# Set test environment before any app imports trigger Settings validation.
os.environ.setdefault("DEBUG", "true")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from transport_matters.config import get_settings  # noqa: E402
from transport_matters.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Ensure each test gets fresh settings (respects per-test env overrides)."""
    get_settings.cache_clear()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
