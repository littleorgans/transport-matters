"""PTY process spawn and teardown helpers for the process supervisor."""

import contextlib
import fcntl
import os
import pty
import signal
import subprocess
import sys
import termios
import threading
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path
    from types import FrameType

from transport_matters.supervisor_models import ManagedProcess
from transport_matters.supervisor_pty import (
    _PTY_JOIN_TIMEOUT,
    _install_parent_cbreak,
    _pty_shuttle,
)


def spawn_with_pty(
    name: str,
    argv: list[str],
    *,
    env: dict[str, str] | None,
    cwd: Path | None,
) -> ManagedProcess:
    """Spawn *argv* attached to a fresh pseudo-terminal.

    If the parent's stdin is not a TTY, silently fall back to
    inherited stdio with a warning. Opening a PTY against a pipe leaves
    the child blocked on a read nobody is driving.
    """
    stdin_fd = sys.stdin.fileno()
    if not os.isatty(stdin_fd):
        warnings.warn(
            "parent stdin is not a tty; spawning with inherited stdio instead of pty",
            RuntimeWarning,
            stacklevel=3,
        )
        popen = subprocess.Popen(
            argv,
            env=env,
            cwd=str(cwd) if cwd is not None else None,
            stdin=None,
            stdout=None,
            stderr=None,
        )
        return ManagedProcess(name=name, popen=popen)

    master_fd, slave_fd = pty.openpty()

    # Best-effort winsize propagation. If either ioctl is unsupported
    # (unusual kernels, some test harnesses) we let the child start
    # with whatever the default PTY sized itself to. The shuttle loop
    # will still work, the cursor geometry will just be wrong until
    # the first SIGWINCH.
    winsize: bytes | None = None
    with contextlib.suppress(OSError):
        winsize = fcntl.ioctl(stdin_fd, termios.TIOCGWINSZ, b"\x00" * 8)
    if winsize is not None:
        with contextlib.suppress(OSError):
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

    # Save the parent's termios state BEFORE we touch the terminal,
    # so teardown can restore the original line discipline. If we
    # cannot read or update it (should never happen on a real TTY
    # but is possible on quirky stdin redirections), bail out of the
    # PTY path and fall back to inherited stdio. Any other behaviour
    # would leave the user's terminal half-reconfigured forever.
    old_attrs: list[Any] | None  # termios attribute list is opaque
    try:
        old_attrs = _install_parent_cbreak(stdin_fd)
    except termios.error:
        os.close(master_fd)
        os.close(slave_fd)
        warnings.warn(
            "could not read parent termios state; falling back to inherited stdio",
            RuntimeWarning,
            stacklevel=3,
        )
        popen = subprocess.Popen(
            argv,
            env=env,
            cwd=str(cwd) if cwd is not None else None,
            stdin=None,
            stdout=None,
            stderr=None,
        )
        return ManagedProcess(name=name, popen=popen)

    stdout_fd = sys.stdout.fileno()
    stop_event = threading.Event()
    shuttle_thread: threading.Thread | None = None
    shuttle_started = False
    prev_sigwinch: Any = None
    pty_popen: subprocess.Popen[bytes] | None = None
    try:
        try:
            pty_popen = subprocess.Popen(
                argv,
                env=env,
                cwd=str(cwd) if cwd is not None else None,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
            )
        finally:
            # Popen dup'd the slave FD into the child across fork/exec;
            # the parent copy is useless to us and keeping it open would
            # prevent the master from reporting EIO when the child exits.
            with contextlib.suppress(OSError):
                os.close(slave_fd)

        # Child output goes to the parent's stdout, not back to stdin.
        # Writing to fd 0 only works on shells that dup it from an
        # O_RDWR /dev/tty handle. fd 1 is the idiomatic target.
        shuttle_thread = threading.Thread(
            target=_pty_shuttle,
            args=(stdin_fd, stdout_fd, master_fd, stop_event),
            name=f"pty-shuttle:{name}",
            daemon=True,
        )

        # SIGWINCH re-propagates the winsize from parent to slave so
        # the child sees resize events live. `signal.signal` returns
        # the previous handler which we stash for restore.
        def _on_sigwinch(_signum: int, _frame: FrameType | None) -> None:
            with contextlib.suppress(OSError):
                ws = fcntl.ioctl(stdin_fd, termios.TIOCGWINSZ, b"\x00" * 8)
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, ws)

        prev_sigwinch = signal.signal(signal.SIGWINCH, _on_sigwinch)
        shuttle_thread.start()
        shuttle_started = True

        return ManagedProcess(
            name=name,
            popen=pty_popen,
            process_group=pty_popen.pid,
            master_fd=master_fd,
            stop_event=stop_event,
            shuttle_thread=shuttle_thread,
            old_termios_attrs=old_attrs,
            prev_sigwinch_handler=prev_sigwinch,
        )
    except Exception:
        stop_event.set()
        if pty_popen is not None and pty_popen.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pty_popen.pid, signal.SIGKILL)
            with contextlib.suppress(Exception):
                pty_popen.wait(timeout=1.0)
        if shuttle_thread is not None and shuttle_started:
            shuttle_thread.join(timeout=_PTY_JOIN_TIMEOUT)
        if prev_sigwinch is not None:
            with contextlib.suppress(Exception):
                signal.signal(signal.SIGWINCH, prev_sigwinch)
        with contextlib.suppress(Exception):
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_attrs)
        with contextlib.suppress(OSError):
            os.close(master_fd)
        raise


def teardown_pty(mp: ManagedProcess) -> None:
    """Release parent-side PTY resources attached to *mp*.

    Safe to call on non-PTY children (no-op) and safe to call twice.
    Each resource is cleared as it is released.
    """
    if mp.stop_event is not None:
        mp.stop_event.set()
    if mp.shuttle_thread is not None:
        # Daemon thread; join best-effort. If it's blocked in a syscall
        # that doesn't honour the stop event we'd rather exit than hang.
        mp.shuttle_thread.join(timeout=_PTY_JOIN_TIMEOUT)
        mp.shuttle_thread = None
    if mp.prev_sigwinch_handler is not None:
        with contextlib.suppress(Exception):
            signal.signal(signal.SIGWINCH, mp.prev_sigwinch_handler)
        mp.prev_sigwinch_handler = None
    if mp.old_termios_attrs is not None:
        # Restore the parent's line discipline. TCSADRAIN waits for
        # queued output to drain first, which matches what `tty.spawn`
        # and friends do.
        with contextlib.suppress(Exception):
            termios.tcsetattr(
                sys.stdin.fileno(),
                termios.TCSADRAIN,
                mp.old_termios_attrs,
            )
        mp.old_termios_attrs = None
    if mp.master_fd is not None:
        with contextlib.suppress(OSError):
            os.close(mp.master_fd)
        mp.master_fd = None
    # stop_event stays set so nobody re-enters the shuttle if the
    # same ManagedProcess is inspected post-teardown.
