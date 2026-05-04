"""Shared fixtures for ``transport_matters.cli`` tests.

Pytest auto-discovers this conftest for every ``test_*.py`` file in the
``cli/`` package. Lifting the fixtures here keeps the per-domain test
modules small and avoids re-defining the same boilerplate in each.

Plain helper functions live in ``_helpers.py`` so this file stays
focused on pytest fixtures and hooks (per the pytest convention).
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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
def tmp_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect both the default storage directory and ``$HOME`` to a temp path.

    Overriding ``MANICURE_STORAGE_DIR`` sandboxes the captured-exchange
    disk. Overriding ``$HOME`` sandboxes the per-workspace lock +
    manifest tree at ``~/.manicure/workspaces/`` so one test run does
    not leak artefacts into the developer's real home directory.
    """
    storage = tmp_path / "manicure-home"
    monkeypatch.setenv("MANICURE_STORAGE_DIR", str(storage))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MANICURE_DEBUG", raising=False)
    # Bust the cached settings so the override actually takes effect.
    from transport_matters import config

    config.get_settings.cache_clear()
    return storage


@pytest.fixture
def spy_run_children(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``_run_children`` with a MagicMock so ``start`` never forks.

    The retry harness in :func:`transport_matters.cli.runner._run_with_retry`
    looks up ``_run_children`` via runner's own module namespace, so
    that is where the patch must land. The package-scope re-export at
    ``transport_matters.cli._run_children`` is unaffected; tests that read
    ``call_args`` against the returned spy work either way.
    """
    spy = MagicMock()
    monkeypatch.setattr("transport_matters.cli.runner._run_children", spy)
    return spy
