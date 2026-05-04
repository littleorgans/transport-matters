"""Process supervisor for the transport-matters CLI.

Owns the lifecycle of child processes spawned by `transport-matters start`:
mitmdump (the reverse proxy) and optionally Claude Code. One child
inherits the terminal (the *foreground* child); others run in the
background with their stdio redirected to a log file.

The supervisor does three things:

1. Spawns named child processes via `subprocess.Popen` with a strict
   stdio policy (either inherit the TTY, redirect to a log file, or
   allocate a real PTY — never two at once).
2. Installs `SIGINT`/`SIGTERM` handlers that request a graceful
   shutdown. Handlers only set a flag; callers check `received_signal`
   in their wait loop and drive termination themselves. This keeps
   the control flow explicit instead of relying on `KeyboardInterrupt`.
3. Reaps surviving children on shutdown: `SIGTERM` first, then
   `SIGKILL` after a grace period. If a child was spawned under a
   PTY, the PTY shuttle thread, termios state and SIGWINCH handler
   are torn down as part of the same path.

Import DAG: this module imports nothing from `transport_matters.*`. It sits
outside the existing `ir → adapters → ... → server` chain and can be
pulled in by `cli.py` (or any other entrypoint) without introducing
a cycle.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import pty
import select
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path
    from types import FrameType

# Sentinel returned from `wait_any`/`wait_one` when a signal — not a
# child exit — broke us out of the wait loop. Keeps the API total:
# every wait returns `(name, code)`, the caller branches on the name.
SIGNAL_EXIT = "__signal__"

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
# generous — if the thread is still blocked after that the daemon flag
# lets the process exit anyway.
_PTY_JOIN_TIMEOUT = 0.5


def _install_parent_cbreak(fd: int) -> list[Any]:
    """Put the parent terminal in cbreak while preserving Return as ``\\r``.

    Python 3.12.2+ changed ``tty.setcbreak()`` to preserve ``ICRNL``.
    That matches ``stty cbreak``, but it also means the parent's line
    discipline rewrites the Return key from ``\\r`` to ``\\n`` before the
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


@dataclass
class ManagedProcess:
    """A child process the supervisor is tracking.

    The PTY-specific fields default to `None` so every existing call
    site (inherited stdio, background log redirect) stays a plain
    `ManagedProcess`. They are populated only by the PTY spawn branch
    and consumed only by `terminate_all`.
    """

    name: str
    popen: subprocess.Popen[bytes]
    log_path: Path | None = None
    process_group: int | None = None
    # PTY state — populated iff the child was spawned with `pty=True`.
    master_fd: int | None = None
    stop_event: threading.Event | None = None
    shuttle_thread: threading.Thread | None = None
    old_termios_attrs: list[Any] | None = field(default=None)  # termios opaque list
    prev_sigwinch_handler: Any = None  # signal handler alias; see _prev_sigint note


class ProcessSupervisor:
    """Spawns and reaps child processes, routing signals to them.

    Not thread-safe. Designed for use from a single control thread
    (the CLI main). All long-lived state is kept in the instance so
    a test can construct a fresh supervisor per case.
    """

    def __init__(self) -> None:
        self._children: dict[str, ManagedProcess] = {}
        self._signal_installed: bool = False
        self._received_signal: int | None = None
        # `signal.signal` returns the previous handler, which is a union
        # of callable / int / None / Handlers enum — `signal._HANDLER` in
        # typeshed, but that alias is private. We store it as `Any` and
        # pass it straight back in `restore_signal_handlers`.
        self._prev_sigint: Any = signal.SIG_DFL  # opaque previous handler
        self._prev_sigterm: Any = signal.SIG_DFL  # opaque previous handler
        self._prev_sighup: Any = signal.SIG_DFL  # opaque previous handler

    # ------------------------------------------------------------- #
    # Introspection                                                 #
    # ------------------------------------------------------------- #

    @property
    def received_signal(self) -> int | None:
        """The signal number delivered to us, or `None` if none yet."""
        return self._received_signal

    def get(self, name: str) -> ManagedProcess:
        """Return the managed process registered under *name*."""
        return self._children[name]

    # ------------------------------------------------------------- #
    # Lifecycle                                                     #
    # ------------------------------------------------------------- #

    def spawn(
        self,
        name: str,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        log_path: Path | None = None,
        foreground: bool = False,
        pty: bool = False,
    ) -> ManagedProcess:
        """Spawn a named child process.

        Exactly one of the following must hold:

        - ``foreground=True`` — stdin/stdout/stderr inherit the parent
          terminal. Use this for the child that owns the TTY (the
          interactive one). Only one child should be foreground at a
          time; the supervisor does not enforce that.
        - ``log_path`` is not ``None`` — stdout and stderr redirect to
          the named file (opened for append), stdin is ``/dev/null``.
          The file is created if missing; the caller owns directory
          creation.

        When ``pty=True`` (which implies ``foreground=True``) the
        child gets a real pseudo-terminal: the supervisor opens a
        master/slave pair, wires the slave side into the child's
        stdio, puts the parent terminal into cbreak mode and runs a
        background shuttle thread that forwards bytes in both
        directions. Ctrl+C still reaches the parent (cbreak preserves
        ISIG) so the existing `received_signal` → `terminate_all`
        shutdown path is unchanged.

        If ``pty=True`` but the parent's stdin is not itself a TTY
        (CI, piped input, a non-interactive `script`-wrapped shell),
        the supervisor falls back to plain inherited stdio and emits
        a one-time ``RuntimeWarning``. Opening a PTY would succeed
        but nothing would be driving the master side, leaving the
        child in a read that never returns.

        Raises ``ValueError`` if the stdio policy is ambiguous,
        ``RuntimeError`` if a process with that name is already live.
        """
        if name in self._children and self._children[name].popen.poll() is None:
            msg = f"process {name!r} is already running"
            raise RuntimeError(msg)
        # PTY axis is validated first so callers get a specific message
        # instead of the generic foreground/log mutex error.
        if pty and not foreground:
            msg = "`pty=True` requires `foreground=True`"
            raise ValueError(msg)
        if pty and log_path is not None:
            msg = "`pty=True` is incompatible with `log_path`"
            raise ValueError(msg)
        if foreground and log_path is not None:
            msg = "`foreground` and `log_path` are mutually exclusive"
            raise ValueError(msg)
        if not foreground and log_path is None:
            msg = "must set `foreground=True` or pass a `log_path`"
            raise ValueError(msg)

        if pty:
            managed = self._spawn_with_pty(name, argv, env=env, cwd=cwd)
            self._children[name] = managed
            return managed

        log_fd: int | None = None
        stdin: int | None
        stdout: int | None
        stderr: int | None
        if foreground:
            # None tells Popen to inherit from the parent process — so
            # claude reads from our tty and writes back to it.
            stdin = None
            stdout = None
            stderr = None
            start_new_session = False
        else:
            # mypy: log_path is non-None in this branch (asserted above).
            assert log_path is not None
            log_fd = os.open(
                str(log_path),
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )
            stdin = subprocess.DEVNULL
            stdout = log_fd
            stderr = subprocess.STDOUT
            # Background children must not share the parent's foreground
            # process group or terminal-generated Ctrl+C will be delivered
            # to them too, racing the supervisor's own signal path.
            start_new_session = True

        try:
            popen = subprocess.Popen(  # noqa: S603 — argv is fully quoted.
                argv,
                env=env,
                cwd=str(cwd) if cwd is not None else None,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                start_new_session=start_new_session,
            )
        finally:
            # Popen dup'd the FD into the child; the parent can let go.
            if log_fd is not None:
                os.close(log_fd)

        managed = ManagedProcess(
            name=name,
            popen=popen,
            log_path=log_path,
            process_group=(popen.pid if start_new_session else None),
        )
        self._children[name] = managed
        return managed

    # ------------------------------------------------------------- #
    # PTY spawn                                                     #
    # ------------------------------------------------------------- #

    def _spawn_with_pty(
        self,
        name: str,
        argv: list[str],
        *,
        env: dict[str, str] | None,
        cwd: Path | None,
    ) -> ManagedProcess:
        """Spawn *argv* attached to a fresh pseudo-terminal.

        If the parent's stdin is not a TTY, silently fall back to
        inherited stdio with a warning — opening a PTY against a
        pipe leaves the child blocked on a read nobody is driving.
        """
        stdin_fd = sys.stdin.fileno()
        if not os.isatty(stdin_fd):
            warnings.warn(
                "parent stdin is not a tty; spawning with inherited stdio "
                "instead of pty",
                RuntimeWarning,
                stacklevel=3,
            )
            popen = subprocess.Popen(  # noqa: S603 — argv is fully quoted.
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
        # with whatever the default PTY sized itself to — the shuttle
        # loop will still work, the cursor geometry will just be wrong
        # until the first SIGWINCH.
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
        # PTY path and fall back to inherited stdio — any other behaviour
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
            popen = subprocess.Popen(  # noqa: S603 — argv is fully quoted.
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
                pty_popen = subprocess.Popen(  # noqa: S603 — argv is fully quoted.
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

            # Child output goes to the parent's stdout, not back to stdin —
            # writing to fd 0 only "works" on shells that dup it from an
            # O_RDWR /dev/tty handle. Under `script`/`expect` or any future
            # harness that opens stdin O_RDONLY, os.write(0, …) returns
            # EBADF and the user sees no output while input still reaches
            # the child. fd 1 is the idiomatic target (matches pty._copy).
            shuttle_thread = threading.Thread(
                target=_pty_shuttle,
                args=(stdin_fd, stdout_fd, master_fd, stop_event),
                name=f"pty-shuttle:{name}",
                daemon=True,
            )

            # SIGWINCH → re-propagate the winsize from parent to slave so
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

    # ------------------------------------------------------------- #
    # Signals                                                       #
    # ------------------------------------------------------------- #

    def install_signal_handlers(self) -> None:
        """Route SIGINT/SIGTERM/SIGHUP to `received_signal` without raising.

        Callers must drive shutdown themselves by checking
        `received_signal` in their wait loop. This keeps the control
        flow explicit and avoids the racy `KeyboardInterrupt` path
        where a second Ctrl+C can arrive mid-cleanup.

        SIGHUP is trapped so that closing the controlling terminal
        (tmux pane close, ssh disconnect) tears down children instead
        of orphaning them holding bound ports.
        """
        if self._signal_installed:
            return
        self._prev_sigint = signal.signal(signal.SIGINT, self._on_signal)
        self._prev_sigterm = signal.signal(signal.SIGTERM, self._on_signal)
        self._prev_sighup = signal.signal(signal.SIGHUP, self._on_signal)
        self._signal_installed = True

    def restore_signal_handlers(self) -> None:
        """Revert signal handlers to whatever was installed before us."""
        if not self._signal_installed:
            return
        signal.signal(signal.SIGINT, self._prev_sigint)
        signal.signal(signal.SIGTERM, self._prev_sigterm)
        signal.signal(signal.SIGHUP, self._prev_sighup)
        self._signal_installed = False

    def _on_signal(self, signum: int, _frame: FrameType | None) -> None:
        # Record the first signal we see; ignore duplicates so the
        # shutdown path runs exactly once.
        if self._received_signal is None:
            self._received_signal = signum

    # ------------------------------------------------------------- #
    # Wait / poll                                                   #
    # ------------------------------------------------------------- #

    def poll_any(self) -> tuple[str, int] | None:
        """Return `(name, returncode)` of an exited child, or `None`."""
        for name, mp in self._children.items():
            rc = mp.popen.poll()
            if rc is not None:
                return name, rc
        return None

    def wait_any(self, poll_interval: float = 0.1) -> tuple[str, int]:
        """Block until one child exits or we catch a signal.

        Returns `(name, returncode)` for the first child to exit, or
        `(SIGNAL_EXIT, signum)` if a signal arrived first. If both
        happened during the same tick, the child exit wins (we report
        what actually happened to the processes).
        """
        while True:
            result = self.poll_any()
            if result is not None:
                return result
            if self._received_signal is not None:
                return SIGNAL_EXIT, self._received_signal
            time.sleep(poll_interval)

    def wait_one(self, name: str, poll_interval: float = 0.1) -> tuple[str, int]:
        """Block until the named child exits or we catch a signal."""
        mp = self._children[name]
        while True:
            rc = mp.popen.poll()
            if rc is not None:
                return name, rc
            if self._received_signal is not None:
                return SIGNAL_EXIT, self._received_signal
            time.sleep(poll_interval)

    # ------------------------------------------------------------- #
    # Shutdown                                                      #
    # ------------------------------------------------------------- #

    def terminate_all(self, *, grace_seconds: float = 5.0) -> None:
        """Terminate every live child; escalate to SIGKILL after grace.

        Idempotent: children that have already exited are skipped.
        PTY resources (shuttle thread, termios, SIGWINCH, master fd)
        are torn down for every child — even those already dead —
        since the parent-side state lives on after the child exits.
        """
        live: list[ManagedProcess] = [
            mp for mp in self._children.values() if mp.popen.poll() is None
        ]
        for mp in live:
            self._signal_child(mp, signal.SIGTERM)

        deadline = time.monotonic() + grace_seconds
        for mp in live:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                mp.popen.wait(timeout=remaining if remaining > 0 else 0.01)
            except subprocess.TimeoutExpired:
                self._signal_child(mp, signal.SIGKILL)
                # Give the kernel a moment to reap the now-killed child.
                # If it doesn't reap within 1s (D-state, slow kernel), we
                # surface a warning rather than silently leak a zombie —
                # init will eventually reap it when the CLI exits, but the
                # user should know something is wrong.
                try:
                    mp.popen.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    warnings.warn(
                        f"process {mp.name!r} (pid={mp.popen.pid}) did not "
                        "reap within 1s after SIGKILL; leaving to init",
                        RuntimeWarning,
                        stacklevel=2,
                    )

        # Tear down every registered child's PTY state regardless of
        # whether this call actually terminated them — the child may
        # have exited earlier and the parent-side resources (termios,
        # SIGWINCH handler, master fd, shuttle thread) are still live.
        # `_teardown_pty` clears the fields so a second `terminate_all`
        # is a no-op on the PTY axis too.
        for mp in self._children.values():
            self._teardown_pty(mp)

    def _signal_child(self, mp: ManagedProcess, signum: signal.Signals) -> None:
        """Deliver *signum* to a child PID or its whole owned process group."""
        if mp.process_group is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(mp.process_group, signum)
            return

        # Child may have exited between the poll and the signal; fine.
        with contextlib.suppress(ProcessLookupError):
            os.kill(mp.popen.pid, signum)

    def _teardown_pty(self, mp: ManagedProcess) -> None:
        """Release parent-side PTY resources attached to *mp*.

        Safe to call on non-PTY children (no-op) and safe to call
        twice — each resource is cleared as it is released.
        """
        if mp.stop_event is not None:
            mp.stop_event.set()
        if mp.shuttle_thread is not None:
            # Daemon thread; join best-effort. If it's blocked in a
            # syscall that doesn't honour the stop event we'd rather
            # exit than hang — hence the short timeout.
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


# ------------------------------------------------------------- #
# PTY shuttle                                                   #
# ------------------------------------------------------------- #


def _pty_shuttle(
    stdin_fd: int,
    stdout_fd: int,
    master_fd: int,
    stop_event: threading.Event,
) -> None:
    """Forward bytes between the parent's terminal and the child's PTY master.

    Parent stdin → master (what the user types reaches the child).
    Master → parent stdout (what the child emits reaches the terminal).

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
      Linux signal that the slave side has closed — the child exited).
    - Either read raises anything else we didn't anticipate.

    A short select timeout keeps the stop event polling responsive so
    teardown doesn't have to wait for keyboard input to unblock us.
    """
    try:
        while not stop_event.is_set():
            try:
                readable, _, _ = select.select(
                    [stdin_fd, master_fd], [], [], _PTY_SELECT_TIMEOUT
                )
            except (OSError, ValueError):
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
