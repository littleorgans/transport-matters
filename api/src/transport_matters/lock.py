"""Workspace lock — advisory mutex for manicure multi-instance support.

Enforces "one live manicure instance per workspace" via ``fcntl.flock``
on a file under the workspace directory. The lock is kernel-held, so it
auto-releases when the owning process dies — no staleness handling
needed on our side.

Usage::

    from transport_matters.lock import WorkspaceLock, WorkspaceLocked

    try:
        with WorkspaceLock(workspace_root) as lock:
            manifest.write(lock.manifest_path, data)
            ...  # spawn children
    except WorkspaceLocked as exc:
        existing = manifest.read(exc.manifest_path)
        ...

On contention, ``__enter__`` raises :class:`WorkspaceLocked` carrying the
paths to both the held lock file and the sibling manifest, so callers
can surface a pointer to the live instance.

`WorkspaceLocked` lives here (not in ``exceptions.py``) because
``exceptions.py`` is populated exclusively with FastAPI-layer HTTP
exceptions. This is a CLI-layer domain exception; colocating it with
the lock keeps the import graph shallow.
"""

from __future__ import annotations

import fcntl
import os
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

__all__ = ["WorkspaceLock", "WorkspaceLocked"]


_LOCK_FILENAME = "lock"
_MANIFEST_FILENAME = "manifest.json"


class WorkspaceLocked(Exception):
    """Raised when another process already holds the workspace lock.

    ``lock_path`` and ``manifest_path`` point at the contested workspace,
    so callers can read the manifest to surface the live PID / ports.
    """

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self.manifest_path = lock_path.parent / _MANIFEST_FILENAME
        super().__init__(f"workspace lock is held: {lock_path}")


class WorkspaceLock:
    """Advisory exclusive lock for a workspace directory.

    Creates ``{root}/lock`` if missing and holds an exclusive ``flock``
    on its file descriptor for the lifetime of the context manager. On
    contention, ``__enter__`` raises :class:`WorkspaceLocked`.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock_path = root / _LOCK_FILENAME
        self.manifest_path = root / _MANIFEST_FILENAME
        self._fd: int | None = None

    def __enter__(self) -> Self:
        self.root.mkdir(parents=True, exist_ok=True)
        # ``flock`` needs an open fd; the file's contents don't matter.
        # ``O_RDWR | O_CREAT`` is safer than ``open(..., "w")`` — the
        # latter would truncate an existing lock file on every acquire,
        # racing briefly with any reader that opens the manifest via
        # the ``lock`` sibling path.
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise WorkspaceLocked(self.lock_path) from exc
        self._fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    @staticmethod
    def is_held(root: Path) -> bool:
        """Return ``True`` if another process currently holds *root*'s lock.

        Read-only probe — never creates the lock file. Used by
        ``manicure list`` to discriminate live instances from stale
        manifests without taking the lock itself.
        """
        lock_path = root / _LOCK_FILENAME
        try:
            fd = os.open(lock_path, os.O_RDWR)
        except FileNotFoundError:
            return False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
                return False
        finally:
            os.close(fd)
