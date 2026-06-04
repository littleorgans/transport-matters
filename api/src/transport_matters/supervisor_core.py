"""Core process supervision logic."""

import contextlib
import os
import signal
import subprocess
import time
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path
    from types import FrameType

from transport_matters.supervisor_models import SIGNAL_EXIT, ManagedProcess
from transport_matters.supervisor_pty_process import spawn_with_pty, teardown_pty


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
        # of callable / int / None / Handlers enum. Typeshed calls that
        # `signal._HANDLER`, but that alias is private. Store it as `Any`
        # and pass it straight back in `restore_signal_handlers`.
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

        - ``foreground=True``: stdin/stdout/stderr inherit the parent
          terminal. Use this for the child that owns the TTY.
        - ``log_path`` is not ``None``: stdout and stderr redirect to
          the named file (opened for append), stdin is ``/dev/null``.
          The file is created if missing; the caller owns directory
          creation.

        When ``pty=True`` (which implies ``foreground=True``) the
        child gets a real pseudo-terminal: the supervisor opens a
        master/slave pair, wires the slave side into the child's
        stdio, puts the parent terminal into cbreak mode and runs a
        background shuttle thread that forwards bytes in both
        directions. Ctrl+C still reaches the parent (cbreak preserves
        ISIG) so the existing `received_signal` -> `terminate_all`
        shutdown path is unchanged.

        If ``pty=True`` but the parent's stdin is not itself a TTY
        (CI, piped input, a non-interactive `script`-wrapped shell),
        the supervisor falls back to plain inherited stdio and emits
        a one-time ``RuntimeWarning``.

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
            managed = spawn_with_pty(name, argv, env=env, cwd=cwd)
            self._children[name] = managed
            return managed

        log_fd: int | None = None
        stdin: int | None
        stdout: int | None
        stderr: int | None
        if foreground:
            # None tells Popen to inherit from the parent process, so
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
            popen = subprocess.Popen(
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
        are torn down for every child, even those already dead, since
        the parent-side state lives on after the child exits.
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
                # surface a warning rather than silently leak a zombie.
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
        # whether this call actually terminated them. The child may
        # have exited earlier and the parent-side resources are still live.
        for mp in self._children.values():
            teardown_pty(mp)

    def _signal_child(self, mp: ManagedProcess, signum: signal.Signals) -> None:
        """Deliver *signum* to a child PID or its whole owned process group."""
        if mp.process_group is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(mp.process_group, signum)
            return

        # Child may have exited between the poll and the signal; fine.
        with contextlib.suppress(ProcessLookupError):
            os.kill(mp.popen.pid, signum)
