"""Shared fixtures for ``transport_matters.cli`` tests.

Pytest auto-discovers this conftest for every ``test_*.py`` file in the
``cli/`` package. Lifting the fixtures here keeps the per-domain test
modules small and avoids re-defining the same boilerplate in each.

Plain helper functions live in ``_helpers.py`` so this file stays
focused on pytest fixtures and hooks (per the pytest convention).
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from transport_matters import config, env_keys
from transport_matters.channel import ChannelSpec
from transport_matters.session.testing import TestDb, database_url_for

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


@pytest.fixture(autouse=True)
def _no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable rich color output globally in tests.

    Typer builds its own `rich.Console` per command, which honours
    `NO_COLOR` (and ignores Click's `CliRunner(color=False)`). Without
    this, CI and any shell with `FORCE_COLOR=1` produce help text with
    ANSI escapes interleaved between `-` characters, breaking plain
    substring assertions like `"--json" in result.output`.
    """
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)


@pytest.fixture
def free_port() -> Iterator[int]:
    """Grab an OS-assigned free port, then immediately release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    yield port


@pytest.fixture
def busy_port() -> Iterator[int]:
    """Bind a port for the duration of the test and yield it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        yield sock.getsockname()[1]


@pytest.fixture
def recently_closed_port() -> Iterator[int]:
    """Yield a port that is closed now but may still be in TIME_WAIT."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port)):
            conn, _addr = listener.accept()
            conn.close()
    yield port


@pytest.fixture
def temporary_channel_database() -> Iterator[TestDb]:
    admin_url = config.resolve_test_database_url(config.Settings.load())
    database_name = f"{config.TEST_DB_PREFIX}channel_{os.getpid()}_{uuid4().hex}"
    test_db = TestDb(admin_url, database_url_for(admin_url, database_name), database_name)
    try:
        yield test_db
    finally:
        test_db.drop()


@pytest.fixture
def channel_spec_factory() -> Callable[[str], ChannelSpec]:
    def factory(database_name: str) -> ChannelSpec:
        return ChannelSpec(
            id="tmp",
            label="Temporary",
            home=Path.home() / ".transport-matters-tmp",
            database_name=database_name,
            proxy_port=18987,
            web_port=18988,
            electron_app_name="Transport Matters Temporary",
            electron_app_id="io.helioy.transport-matters.temporary",
            electron_user_data=None,
            dock_icon="default",
            badge=None,
        )

    return factory


@pytest.fixture
def patch_channel_specs(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., None]:
    def patch(*specs: ChannelSpec) -> None:
        import transport_matters.channel as channel_module

        monkeypatch.setattr(channel_module, "_channel_specs", lambda: tuple(specs))
        monkeypatch.setattr(
            channel_module,
            "_channel_specs_by_id",
            lambda: {spec.id: spec for spec in specs},
        )

    return patch


@pytest.fixture
def point_cli_at_channel_database(
    channel_spec_factory: Callable[[str], ChannelSpec],
    patch_channel_specs: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., ChannelSpec]:
    def point(test_db: TestDb, *, home: Path | None = None) -> ChannelSpec:
        spec = channel_spec_factory(test_db.database_name)
        patch_channel_specs(spec)
        if home is not None:
            monkeypatch.setenv(env_keys.HOME, str(home))
        monkeypatch.setenv(env_keys.CHANNEL, spec.id)
        monkeypatch.setenv(env_keys.DATABASE_URL, test_db.admin_url)
        config.get_settings.cache_clear()
        return spec

    return point


@pytest.fixture
def tmp_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect both the default storage directory and ``$HOME`` to a temp path.

    Overriding ``TRANSPORT_MATTERS_STORAGE_DIR`` sandboxes the captured-exchange
    disk. Overriding ``$HOME`` sandboxes the per-workspace lock +
    manifest tree at ``~/.transport-matters/workspaces/`` so one test run does
    not leak artefacts into the developer's real home directory.
    """
    storage = tmp_path / "manicure-home"
    monkeypatch.setenv("TRANSPORT_MATTERS_STORAGE_DIR", str(storage))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TRANSPORT_MATTERS_DEBUG", raising=False)
    # Bust the cached settings so the override actually takes effect.
    from transport_matters import config

    config.get_settings.cache_clear()
    return storage


@pytest.fixture(autouse=True)
def _stub_launch_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op the shared session-store preflight for all CLI tests.

    The launch lifecycles (``run_start``/``run_codex``) hard-block when the session
    store is unreachable. These CLI tests exercise launch *mechanics*, not the DB gate,
    and must not require a live runtime Postgres — CI provides only the TEST database, so
    any test that invokes a real launch (without ``--print-command``) would otherwise
    exit 2 with "cannot reach the session store". Each lifecycle imports the name into its
    own module, so the patch lands there. The gate itself is covered directly in
    ``test_launch_preflight.py`` and end-to-end in the integration launch smoke.
    """
    monkeypatch.setattr(
        "transport_matters.cli.start_cmd.preflight_session_store_or_exit", lambda: None
    )
    monkeypatch.setattr(
        "transport_matters.cli.codex_cmd.preflight_session_store_or_exit", lambda: None
    )


@pytest.fixture
def spy_run_client_children(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``_run_client_children`` so ``start`` never forks.

    The shared retry harness looks up ``_run_client_children`` via
    runner's own module namespace, so that is where the patch must land.
    """
    spy = MagicMock()
    monkeypatch.setattr("transport_matters.cli.runner._run_client_children", spy)
    return spy
