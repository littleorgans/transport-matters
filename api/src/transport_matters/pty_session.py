"""PTY process and file descriptor primitives."""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

CHILD_EXIT_TIMEOUT_S = 1.0
_TERMINAL_CHILD_DEFAULT_SIGNALS = (
    signal.SIGHUP,
    signal.SIGINT,
    signal.SIGQUIT,
    signal.SIGTERM,
    signal.SIGTSTP,
    signal.SIGTTIN,
    signal.SIGTTOU,
)


class _WinsizeSetter(Protocol):
    def __call__(self, fd: int, *, cols: int, rows: int) -> None:
        pass


WinsizeSetter = _WinsizeSetter


@dataclass(slots=True)
class TerminalPty:
    """One child process attached to one PTY master."""

    master_fd: int
    process: subprocess.Popen[bytes]
    closed: bool = False


def spawn_pty_process(
    *,
    argv: Sequence[str],
    env: Mapping[str, str],
    cwd: Path,
    cols: int,
    rows: int,
) -> TerminalPty:
    """Spawn one process attached to a PTY with browser terminal job control."""
    if not argv:
        raise ValueError("PTY process argv must not be empty")

    master_fd, slave_fd = pty.openpty()
    try:
        set_winsize(slave_fd, cols=cols, rows=rows)
        process = subprocess.Popen(
            list(argv),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env=dict(env),
            preexec_fn=prepare_terminal_child(slave_fd),
            close_fds=True,
        )
    except Exception:
        close_fd(slave_fd)
        close_fd(master_fd)
        raise

    close_fd(slave_fd)
    return TerminalPty(master_fd=master_fd, process=process)


def prepare_terminal_child(slave_fd: int) -> Callable[[], None]:
    def prepare() -> None:
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.tcsetpgrp(slave_fd, os.getpgrp())
        for child_signal in _TERMINAL_CHILD_DEFAULT_SIGNALS:
            signal.signal(child_signal, signal.SIG_DFL)

    return prepare


def set_winsize(fd: int, *, cols: int, rows: int) -> None:
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)


def write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        try:
            written = os.write(fd, data[offset:])
        except OSError as exc:
            if exc.errno in {errno.EIO, errno.EBADF}:
                return
            raise
        if written <= 0:
            raise RuntimeError("terminal PTY write returned no progress")
        offset += written


def terminate_terminal_pty(session: TerminalPty) -> None:
    process = session.process
    if process.poll() is None:
        terminate_process_group(process)
    close_terminal_master(session)


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=CHILD_EXIT_TIMEOUT_S)
        return
    except subprocess.TimeoutExpired:
        pass

    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=CHILD_EXIT_TIMEOUT_S)


def close_terminal_master(session: TerminalPty) -> None:
    if session.closed:
        return
    close_fd(session.master_fd)
    session.closed = True


def close_fd(fd: int) -> None:
    with contextlib.suppress(OSError):
        os.close(fd)
