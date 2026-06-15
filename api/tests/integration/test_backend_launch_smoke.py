"""Live-launch smoke tests for the session-store readiness contract.

These exercise the REAL launch shape (subprocess), not an in-process TestClient with
the default storage dir, because the original bug only manifested when a launch sets a
per-run ``STORAGE_DIR`` into the child env (in-process TestClient hid it). Two guards:

* bug #3: a launched backend resolves operator config (settings.toml -> DB url) from
  ``$TRANSPORT_MATTERS_HOME``, NOT the per-run ``STORAGE_DIR`` a launch injects. With the
  bug, ``GET /v1/sessions`` 503s; fixed, it serves an empty sessions envelope.
* no-DB fail-fast: the shared launch preflight hard-blocks a launch (non-zero exit with
  guidance) when the session store is unreachable, before spawning anything.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from transport_matters.config import MissingDatabaseConfigError
from transport_matters.session.testing import TestDb


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _poll_http(url: str, timeout: float = 30.0) -> tuple[int, bytes]:
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 - fixed localhost URL
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, OSError) as exc:
            last_err = exc
            time.sleep(0.25)
    raise AssertionError(f"backend never responded at {url}: {last_err}")


@pytest.fixture
def migrated_db() -> Iterator[TestDb]:
    try:
        db = TestDb.create()
    except MissingDatabaseConfigError:
        pytest.skip("no test database configured (set TRANSPORT_MATTERS_TEST_DATABASE_URL)")
    try:
        yield db
    finally:
        db.drop()


def test_launched_backend_reads_db_from_home_not_per_run_storage(
    tmp_path: Path, migrated_db: TestDb
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.toml").write_text(
        f'[database]\nurl = "{migrated_db.database_url}"\n', encoding="utf-8"
    )
    per_run = tmp_path / "run-storage"
    per_run.mkdir()
    port = _free_port()

    env = {
        **os.environ,
        "TRANSPORT_MATTERS_HOME": str(home),
        "TRANSPORT_MATTERS_STORAGE_DIR": str(per_run),  # the per-run dir a launch injects
        "TRANSPORT_MATTERS_WEB_PORT": str(port),
    }
    # Force resolution through HOME/settings.toml (the bug-#3 path), not an env override.
    env.pop("TRANSPORT_MATTERS_DATABASE_URL", None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "transport_matters.main:app", "--host", "127.0.0.1",
         "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        status, body = _poll_http(
            f"http://127.0.0.1:{port}/v1/sessions?owner=local&limit=50"
        )
        assert status == 200, body
        assert json.loads(body) == {"items": [], "nextCursor": None}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def test_launch_preflight_blocks_when_session_store_unreachable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    per_run = tmp_path / "run-storage"
    per_run.mkdir()

    env = {
        **os.environ,
        "TRANSPORT_MATTERS_HOME": str(home),
        "TRANSPORT_MATTERS_STORAGE_DIR": str(per_run),
        # Unreachable on purpose: preflight must hard-block before spawning anything.
        "TRANSPORT_MATTERS_DATABASE_URL": "postgresql://u:p@127.0.0.1:1/none",
    }

    result = subprocess.run(
        [sys.executable, "-m", "transport_matters.cli", "claude", "--no-claude"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    combined = (result.stdout + result.stderr).lower()
    assert "session store" in combined
    assert "docker compose" in combined or "transport_matters_database_url" in combined
