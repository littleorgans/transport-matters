import os

# Set test environment before any app imports trigger Settings validation.
os.environ.setdefault("DEBUG", "true")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from transport_matters import env_keys  # noqa: E402
from transport_matters.config import get_settings  # noqa: E402
from transport_matters.main import create_app  # noqa: E402

# Non-prefixed process-env vars a *live* Transport Matters session exports into every
# shell it spawns (proxy wiring + the managed agent homes). These have no ``env_prefix``
# to key off, so they are scrubbed by explicit name.
_INHERITED_LEAK_KEYS = (
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)

# ``TRANSPORT_MATTERS_*`` keys that are legitimate *test-infra* config, not per-run
# contamination: the session-store suite resolves its Postgres URL from these (commonly
# exported by direnv). Scrubbing them would turn every ``session/`` test into a
# ``MissingDatabaseConfigError``. ``HOME`` is preserved too, though the isolate fixture
# below repoints it regardless.
_PRESERVED_PREFIX_KEYS = frozenset(
    {
        env_keys.HOME,
        env_keys.DATABASE_URL,
        env_keys.TEST_DATABASE_URL,
        env_keys.DOCKER_PG_PORT,
    }
)


@pytest.fixture(autouse=True)
def _scrub_inherited_session_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the suite hermetic regardless of where it is launched.

    The captured-run workflow runs agents (and any shell they spawn) from inside a live
    TM session, which exports its own ``TRANSPORT_MATTERS_*`` config plus proxy/agent-home
    vars. pydantic ``Settings`` reads the prefix directly, so those values override test
    defaults and fail tests that assert the shipped defaults, child-env shape, or
    overlay-seed identity. Strip the prefix (except the test-infra DB config in
    ``_PRESERVED_PREFIX_KEYS``) and the known non-prefixed leak vars before each test;
    fixtures and tests that need specific values re-set them via their own monkeypatch.
    Ordered first so the env-setting fixtures below re-establish cleanly."""
    for key in [k for k in os.environ if k.startswith(env_keys.ENV_PREFIX)]:
        if key in _PRESERVED_PREFIX_KEYS:
            continue
        monkeypatch.delenv(key, raising=False)
    for key in _INHERITED_LEAK_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_transport_matters_home(
    _scrub_inherited_session_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
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
def _trusted_test_hosts(
    _scrub_inherited_session_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
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
