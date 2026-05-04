"""Tests for the workspace lock."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from transport_matters.lock import WorkspaceLock, WorkspaceLocked

if TYPE_CHECKING:
    from pathlib import Path

# --------------------------------------------------------------------------- #
# Basic acquire / release                                                     #
# --------------------------------------------------------------------------- #


def test_lock_creates_lock_file(tmp_path: Path) -> None:
    with WorkspaceLock(tmp_path) as lock:
        assert lock.lock_path.exists()
        assert lock.lock_path.parent == tmp_path


def test_lock_creates_root_if_missing(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    assert not nested.exists()
    with WorkspaceLock(nested):
        assert nested.is_dir()


def test_lock_releases_on_exit(tmp_path: Path) -> None:
    with WorkspaceLock(tmp_path):
        pass
    # Release on normal exit — second acquire must succeed.
    with WorkspaceLock(tmp_path):
        pass


def test_lock_releases_on_exception(tmp_path: Path) -> None:
    class Boom(Exception):
        pass

    with pytest.raises(Boom), WorkspaceLock(tmp_path):
        raise Boom
    # Exception path still releases.
    with WorkspaceLock(tmp_path):
        pass


# --------------------------------------------------------------------------- #
# Contention                                                                  #
# --------------------------------------------------------------------------- #


def test_double_acquire_raises_workspace_locked(tmp_path: Path) -> None:
    with (
        WorkspaceLock(tmp_path),
        pytest.raises(WorkspaceLocked),
        WorkspaceLock(tmp_path),
    ):
        pass


def test_workspace_locked_exposes_manifest_path(tmp_path: Path) -> None:
    with WorkspaceLock(tmp_path):
        try:
            with WorkspaceLock(tmp_path):
                pytest.fail("expected WorkspaceLocked")
        except WorkspaceLocked as exc:
            assert exc.lock_path == tmp_path / "lock"
            assert exc.manifest_path == tmp_path / "manifest.json"


def test_two_different_roots_do_not_contend(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    with WorkspaceLock(a), WorkspaceLock(b):
        pass


# --------------------------------------------------------------------------- #
# Release-on-death                                                            #
# --------------------------------------------------------------------------- #


def test_lock_releases_when_holder_process_dies(tmp_path: Path) -> None:
    """fcntl.flock is kernel-held: when the owning process dies, all its
    fds close and the lock releases automatically. No cleanup on our end.
    """
    child_src = (
        "import time\n"
        "from pathlib import Path\n"
        "from transport_matters.lock import WorkspaceLock\n"
        f"lock = WorkspaceLock(Path({str(tmp_path)!r}))\n"
        "lock.__enter__()\n"
        "print('LOCKED', flush=True)\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen(  # noqa: S603 — launching our own interpreter with a known script
        [sys.executable, "-c", child_src],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert proc.stdout is not None  # for type narrowing
        ready = proc.stdout.readline().decode().strip()
        assert ready == "LOCKED", f"unexpected child output: {ready!r}"

        # While the child holds the lock, the parent cannot acquire.
        with pytest.raises(WorkspaceLocked), WorkspaceLock(tmp_path):
            pass

        # Kill the child abruptly — no context-manager exit runs.
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=2)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)

    # The kernel may take a tick to reclaim the fd; poll briefly before
    # giving up.
    deadline = time.monotonic() + 2.0
    last_exc: WorkspaceLocked | None = None
    while time.monotonic() < deadline:
        try:
            with WorkspaceLock(tmp_path):
                return
        except WorkspaceLocked as exc:
            last_exc = exc
            time.sleep(0.05)
    raise AssertionError("lock was not released after child death") from last_exc
