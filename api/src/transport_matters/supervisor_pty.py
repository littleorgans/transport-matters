"""PTY terminal helpers for the process supervisor."""

import contextlib
import os
import select
import termios
import tty
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import threading

# Chunk size for the PTY shuttle. 1024 is the same size the stdlib's
# `pty.spawn` uses; it balances syscall overhead against tail latency
# on interactive echo.
_PTY_CHUNK_SIZE = 1024

# Select timeout for the shuttle loop. Short enough that a terminate
# request is honoured promptly, long enough that we don't burn CPU
# on an idle tty.
_PTY_SELECT_TIMEOUT = 0.1

# Join timeout for the shuttle thread during teardown. The loop is
# expected to exit on its next select tick, so half a second is very
# generous. If the thread is still blocked after that, the daemon flag
# lets the process exit anyway.
_PTY_JOIN_TIMEOUT = 0.5


def _install_parent_cbreak(fd: int) -> list[Any]:
    """Put the parent terminal in cbreak while preserving Return as ``\r``.

    Python 3.12.2+ changed ``tty.setcbreak()`` to preserve ``ICRNL``.
    That matches ``stty cbreak``, but it also means the parent's line
    discipline rewrites the Return key from ``\r`` to ``\n`` before the
    PTY shuttle forwards it into the child. Full-screen CLIs like Claude
    distinguish those bytes, so install cbreak manually and clear
    ``ICRNL`` while still leaving ``ISIG`` enabled.
    """
    old_attrs = termios.tcgetattr(fd)
    new_attrs = list(old_attrs)
    tty.cfmakecbreak(new_attrs)
    new_attrs[tty.IFLAG] &= ~termios.ICRNL
    termios.tcsetattr(fd, termios.TCSAFLUSH, new_attrs)
    return old_attrs


def _pty_shuttle(
    stdin_fd: int,
    stdout_fd: int,
    master_fd: int,
    stop_event: threading.Event,
) -> None:
    """Forward bytes between the parent's terminal and the child's PTY master.

    Parent stdin -> master: what the user types reaches the child.
    Master -> parent stdout: what the child emits reaches the terminal.

    The two FDs are named separately even though on most interactive
    shells they're dup'd from the same /dev/tty handle: writing to
    `stdin_fd` is correct only as long as that handle is ``O_RDWR``,
    which is a coincidence of how the shell opens the tty. Under
    ``script``/``expect`` harnesses, redirected stdin, or anything
    future that opens stdin ``O_RDONLY``, writing to it would return
    ``EBADF`` and silently swallow the child's output. Writing to
    ``stdout_fd`` is what the stdlib's own ``pty._copy`` does.

    Runs in a daemon thread. Exits on any of:

    - ``stop_event`` set (teardown path).
    - ``master_fd`` returns EOF / ``OSError`` with ``EIO`` (the canonical
      Linux signal that the slave side has closed, the child exited).
    - Either read raises anything else we didn't anticipate.

    A short select timeout keeps the stop event polling responsive so
    teardown doesn't have to wait for keyboard input to unblock us.
    """
    try:
        while not stop_event.is_set():
            try:
                readable, _, _ = select.select([stdin_fd, master_fd], [], [], _PTY_SELECT_TIMEOUT)
            except OSError, ValueError:
                # select can raise OSError/ValueError if a fd was
                # closed underneath us during teardown; treat it as
                # a stop signal.
                return
            if stop_event.is_set():
                return
            if stdin_fd in readable:
                try:
                    data = os.read(stdin_fd, _PTY_CHUNK_SIZE)
                except OSError:
                    return
                if not data:
                    return
                with contextlib.suppress(OSError):
                    os.write(master_fd, data)
            if master_fd in readable:
                try:
                    data = os.read(master_fd, _PTY_CHUNK_SIZE)
                except OSError:
                    # EIO on Linux once the slave side closes, EBADF
                    # if teardown got there first. Either way, we're
                    # done.
                    return
                if not data:
                    return
                with contextlib.suppress(OSError):
                    os.write(stdout_fd, data)
    finally:
        # Belt and braces: if the caller forgot to set the stop event
        # (e.g. we returned on EOF), mark it set so teardown fast-paths.
        stop_event.set()
