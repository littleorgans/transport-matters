"""Tests for `manicure.supervisor`.

Hermetic: no real subprocesses are spawned. A `FakePopen` stands in
for `subprocess.Popen`, and we drive state transitions by mutating
its `returncode` (and the two `_die_on_*` flags that control what
`terminate()` / `kill()` do to the returncode).

The signal path is exercised by calling `ProcessSupervisor._on_signal`
directly instead of sending real signals — that keeps the tests
deterministic and avoids cross-talk between pytest's signal handling
and ours.
"""

from __future__ import annotations

import signal
import subprocess
import termios
import tty
from typing import TYPE_CHECKING, Any

import pytest

from manicure.supervisor import (
    SIGNAL_EXIT,
    ManagedProcess,
    ProcessSupervisor,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# --------------------------------------------------------------------------- #
# Fake Popen                                                                  #
# --------------------------------------------------------------------------- #


class FakePopen:
    """Stand-in for `subprocess.Popen` that never forks a real process.

    Exposes only what `ProcessSupervisor` touches. Tests mutate
    `returncode` directly to simulate child exits, and toggle
    `_die_on_terminate` / `_die_on_kill` to control how the fake
    responds to signals sent via `terminate()` / `kill()`.
    """

    # Class-level registry so tests can peek at every instance created.
    instances: list[FakePopen] = []
    killpg_calls: list[tuple[int, int]] = []
    kill_calls_by_pid: list[tuple[int, int]] = []
    _next_pid: int = 12_345

    def __init__(
        self,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        stdin: Any = None,
        stdout: Any = None,
        stderr: Any = None,
        **_extra: Any,
    ) -> None:
        self.argv = argv
        self.env = env
        self.cwd = cwd
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.extra = _extra
        self.returncode: int | None = None
        self.terminate_calls: int = 0
        self.kill_calls: int = 0
        self.wait_calls: list[float | None] = []
        self.pid: int = FakePopen._next_pid
        FakePopen._next_pid += 1
        # Controlled by tests. Defaults: terminate is a no-op (simulates
        # a stubborn child that needs SIGKILL); kill actually reaps.
        self._die_on_terminate: bool = False
        self._die_on_kill: bool = True
        FakePopen.instances.append(self)

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self._die_on_terminate and self.returncode is None:
            self.returncode = 0

    def kill(self) -> None:
        self.kill_calls += 1
        if self._die_on_kill and self.returncode is None:
            self.returncode = -int(signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0.0)
        return self.returncode


@pytest.fixture(autouse=True)
def _reset_fake_popen_registry() -> Iterator[None]:
    """Clear the class-level registry between tests."""
    FakePopen.instances.clear()
    FakePopen.killpg_calls.clear()
    FakePopen.kill_calls_by_pid.clear()
    FakePopen._next_pid = 12_345
    yield
    FakePopen.instances.clear()
    FakePopen.killpg_calls.clear()
    FakePopen.kill_calls_by_pid.clear()


@pytest.fixture
def patched_popen(monkeypatch: pytest.MonkeyPatch) -> type[FakePopen]:
    """Replace `subprocess.Popen` inside the supervisor module."""
    FakePopen.instances.clear()
    FakePopen.killpg_calls.clear()
    FakePopen.kill_calls_by_pid.clear()
    FakePopen._next_pid = 12_345

    def _fake_killpg(pgid: int, signum: int) -> None:
        FakePopen.killpg_calls.append((pgid, signum))
        for inst in FakePopen.instances:
            if inst.pid != pgid or inst.returncode is not None:
                continue
            if signum == int(signal.SIGTERM) and inst._die_on_terminate:
                inst.returncode = 0
            if signum == int(signal.SIGKILL) and inst._die_on_kill:
                inst.returncode = -int(signal.SIGKILL)
            if signum not in {int(signal.SIGTERM), int(signal.SIGKILL)}:
                inst.returncode = -int(signum)

    def _fake_kill(pid: int, signum: int) -> None:
        FakePopen.kill_calls_by_pid.append((pid, signum))
        for inst in FakePopen.instances:
            if inst.pid != pid or inst.returncode is not None:
                continue
            if signum == int(signal.SIGTERM) and inst._die_on_terminate:
                inst.returncode = 0
            elif signum == int(signal.SIGKILL) and inst._die_on_kill:
                inst.returncode = -int(signal.SIGKILL)
            else:
                inst.returncode = -int(signum)

    monkeypatch.setattr("manicure.supervisor.subprocess.Popen", FakePopen)
    monkeypatch.setattr("manicure.supervisor.os.killpg", _fake_killpg)
    monkeypatch.setattr("manicure.supervisor.os.kill", _fake_kill)
    return FakePopen


@pytest.fixture
def tmp_log(tmp_path: Path) -> Path:
    """A path inside `tmp_path` suitable for log-redirect tests."""
    return tmp_path / "child.log"


# --------------------------------------------------------------------------- #
# spawn: stdio policy                                                         #
# --------------------------------------------------------------------------- #


def test_spawn_foreground_inherits_stdio(patched_popen: type[FakePopen]) -> None:
    sup = ProcessSupervisor()
    sup.spawn("claude", ["claude"], foreground=True)

    assert len(FakePopen.instances) == 1
    fp = FakePopen.instances[0]
    # `None` on Popen stdio means inherit the parent — that's how claude
    # gets the real terminal.
    assert fp.stdin is None
    assert fp.stdout is None
    assert fp.stderr is None


def test_spawn_background_redirects_to_log(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)

    fp = FakePopen.instances[0]
    # stdin goes to /dev/null, stderr is merged into stdout, stdout is
    # a real FD pointing at the log file.
    assert fp.stdin == subprocess.DEVNULL
    assert fp.stderr == subprocess.STDOUT
    assert isinstance(fp.stdout, int)
    assert fp.extra["start_new_session"] is True
    assert mp.process_group == fp.pid
    # The file was created and is writable.
    assert tmp_log.exists()


def test_spawn_rejects_both_foreground_and_log(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    with pytest.raises(ValueError, match="mutually exclusive"):
        sup.spawn("x", ["x"], foreground=True, log_path=tmp_log)


def test_spawn_rejects_neither_foreground_nor_log(
    patched_popen: type[FakePopen],
) -> None:
    sup = ProcessSupervisor()
    with pytest.raises(ValueError, match="foreground"):
        sup.spawn("x", ["x"])


def test_spawn_rejects_duplicate_live_name(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    with pytest.raises(RuntimeError, match="already running"):
        sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)


def test_spawn_allows_reuse_of_name_after_exit(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    first = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    first.popen.returncode = 0  # simulate clean exit  # type: ignore[attr-defined]
    # Second spawn with same name now succeeds.
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    assert len(FakePopen.instances) == 2


def test_spawn_records_cwd_and_env(
    patched_popen: type[FakePopen], tmp_log: Path, tmp_path: Path
) -> None:
    sup = ProcessSupervisor()
    sup.spawn(
        "mitmdump",
        ["mitmdump", "--foo"],
        env={"A": "1"},
        cwd=tmp_path,
        log_path=tmp_log,
    )
    fp = FakePopen.instances[0]
    assert fp.argv == ["mitmdump", "--foo"]
    assert fp.env == {"A": "1"}
    assert fp.cwd == str(tmp_path)


# --------------------------------------------------------------------------- #
# poll_any / wait_any / wait_one                                              #
# --------------------------------------------------------------------------- #


def test_poll_any_returns_none_when_all_live(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    sup.spawn("claude", ["claude"], foreground=True)
    assert sup.poll_any() is None


def test_poll_any_returns_exited_child(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp = sup.spawn("claude", ["claude"], foreground=True)
    mp.popen.returncode = 7
    result = sup.poll_any()
    assert result == ("claude", 7)


def test_wait_any_returns_first_exited(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    mp_mitm = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    sup.spawn("claude", ["claude"], foreground=True)
    mp_mitm.popen.returncode = 1
    assert sup.wait_any(poll_interval=0.001) == ("mitmdump", 1)


def test_wait_any_returns_signal_sentinel(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    # Simulate SIGINT delivery without actually raising a signal — avoids
    # pytest's own signal handler cleanup paths.
    sup._on_signal(signal.SIGINT, None)
    name, rc = sup.wait_any(poll_interval=0.001)
    assert name == SIGNAL_EXIT
    assert rc == int(signal.SIGINT)


def test_wait_any_prefers_child_exit_over_signal(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    """If a child is already dead AND a signal is pending, report the
    child exit — the caller needs to know what the children actually did."""
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp.popen.returncode = 0
    sup._on_signal(signal.SIGINT, None)
    name, rc = sup.wait_any(poll_interval=0.001)
    assert name == "mitmdump"
    assert rc == 0


def test_wait_one_ignores_other_children(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    mp_mitm = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp_cc = sup.spawn("claude", ["claude"], foreground=True)
    # mitmdump exits; wait_one("claude") should NOT return yet.
    mp_mitm.popen.returncode = 0
    # Flip claude's rc so wait_one returns.
    mp_cc.popen.returncode = 5
    assert sup.wait_one("claude", poll_interval=0.001) == ("claude", 5)


def test_wait_one_returns_signal_sentinel(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    sup._on_signal(signal.SIGTERM, None)
    name, rc = sup.wait_one("mitmdump", poll_interval=0.001)
    assert name == SIGNAL_EXIT
    assert rc == int(signal.SIGTERM)


# --------------------------------------------------------------------------- #
# signal handlers                                                             #
# --------------------------------------------------------------------------- #


def test_install_and_restore_signal_handlers(
    patched_popen: type[FakePopen],
) -> None:
    prev_sigint = signal.getsignal(signal.SIGINT)
    prev_sigterm = signal.getsignal(signal.SIGTERM)

    sup = ProcessSupervisor()
    sup.install_signal_handlers()
    try:
        assert signal.getsignal(signal.SIGINT) != prev_sigint
        assert signal.getsignal(signal.SIGTERM) != prev_sigterm
    finally:
        sup.restore_signal_handlers()

    assert signal.getsignal(signal.SIGINT) == prev_sigint
    assert signal.getsignal(signal.SIGTERM) == prev_sigterm


def test_install_signal_handlers_is_idempotent(
    patched_popen: type[FakePopen],
) -> None:
    sup = ProcessSupervisor()
    sup.install_signal_handlers()
    try:
        after_first = signal.getsignal(signal.SIGINT)
        sup.install_signal_handlers()
        assert signal.getsignal(signal.SIGINT) == after_first
    finally:
        sup.restore_signal_handlers()


def test_on_signal_records_first_only(patched_popen: type[FakePopen]) -> None:
    sup = ProcessSupervisor()
    assert sup.received_signal is None
    sup._on_signal(signal.SIGINT, None)
    assert sup.received_signal == int(signal.SIGINT)
    # Second signal is ignored so the shutdown path runs exactly once.
    sup._on_signal(signal.SIGTERM, None)
    assert sup.received_signal == int(signal.SIGINT)


# --------------------------------------------------------------------------- #
# terminate_all                                                               #
# --------------------------------------------------------------------------- #


def test_terminate_all_sends_sigterm_and_waits(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp.popen._die_on_terminate = True  # type: ignore[attr-defined]

    sup.terminate_all(grace_seconds=0.01)

    fake = _as_fake(mp)
    assert FakePopen.killpg_calls == [(fake.pid, int(signal.SIGTERM))]
    assert fake.terminate_calls == 0
    assert fake.kill_calls == 0
    assert fake.returncode == 0


def test_terminate_all_escalates_to_sigkill(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    # Stubborn child: ignores terminate, only dies on kill.
    mp.popen._die_on_terminate = False  # type: ignore[attr-defined]
    mp.popen._die_on_kill = True  # type: ignore[attr-defined]

    sup.terminate_all(grace_seconds=0.01)

    fake = _as_fake(mp)
    assert FakePopen.killpg_calls == [
        (fake.pid, int(signal.SIGTERM)),
        (fake.pid, int(signal.SIGKILL)),
    ]
    assert fake.terminate_calls == 0
    assert fake.kill_calls == 0
    assert fake.returncode == -int(signal.SIGKILL)


def test_terminate_all_skips_already_dead(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp.popen.returncode = 0

    sup.terminate_all(grace_seconds=0.01)

    fake = _as_fake(mp)
    assert FakePopen.killpg_calls == []
    assert fake.terminate_calls == 0
    assert fake.kill_calls == 0


def test_terminate_all_is_idempotent(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp.popen._die_on_terminate = True  # type: ignore[attr-defined]

    sup.terminate_all(grace_seconds=0.01)
    sup.terminate_all(grace_seconds=0.01)  # second pass should be a no-op

    fake = _as_fake(mp)
    assert FakePopen.killpg_calls == [(fake.pid, int(signal.SIGTERM))]
    assert fake.terminate_calls == 0


def test_terminate_all_handles_multiple_children(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    mp_mitm = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp_cc = sup.spawn("claude", ["claude"], foreground=True)
    mp_mitm.popen._die_on_terminate = True  # type: ignore[attr-defined]
    mp_cc.popen._die_on_terminate = True  # type: ignore[attr-defined]

    sup.terminate_all(grace_seconds=0.01)

    assert FakePopen.killpg_calls == [(mp_mitm.popen.pid, int(signal.SIGTERM))]
    assert FakePopen.kill_calls_by_pid == [(mp_cc.popen.pid, int(signal.SIGTERM))]
    assert _as_fake(mp_mitm).terminate_calls == 0
    assert _as_fake(mp_cc).terminate_calls == 0


def test_terminate_all_warns_if_child_survives_sigkill(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    """Belt-and-suspenders: if the kernel doesn't reap within 1s of
    SIGKILL (D-state, ptrace, exotic scheduler), surface a warning
    rather than silently leaving a zombie for init to collect later.
    """
    import warnings

    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    # Neither signal clears the returncode in FakePopen — wait() keeps
    # raising TimeoutExpired, which is exactly the stuck-zombie scenario.
    mp.popen._die_on_terminate = False  # type: ignore[attr-defined]
    mp.popen._die_on_kill = False  # type: ignore[attr-defined]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sup.terminate_all(grace_seconds=0.01)

    runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert len(runtime_warnings) == 1
    msg = str(runtime_warnings[0].message)
    assert "mitmdump" in msg
    assert "SIGKILL" in msg


# --------------------------------------------------------------------------- #
# get                                                                         #
# --------------------------------------------------------------------------- #


def test_get_returns_managed_process(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    assert sup.get("mitmdump") is mp


def test_get_unknown_name_raises(patched_popen: type[FakePopen]) -> None:
    sup = ProcessSupervisor()
    with pytest.raises(KeyError):
        sup.get("ghost")


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _as_fake(mp: ManagedProcess) -> FakePopen:
    """Narrow `mp.popen` to `FakePopen` for test assertions."""
    assert isinstance(mp.popen, FakePopen)
    return mp.popen


# --------------------------------------------------------------------------- #
# PTY spawn                                                                   #
# --------------------------------------------------------------------------- #


class _StubThread:
    """Stand-in for `threading.Thread` used in the PTY shuttle tests.

    Records creation and `start()` / `join()` calls without actually
    running the target, so tests don't race a real background loop
    against mocked file descriptors.
    """

    instances: list[_StubThread] = []

    def __init__(
        self,
        *,
        target: Any = None,
        args: tuple[Any, ...] = (),
        name: str = "",
        daemon: bool = False,
    ) -> None:
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon
        self.started: bool = False
        self.join_calls: list[float | None] = []
        _StubThread.instances.append(self)

    def start(self) -> None:
        self.started = True

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)


@pytest.fixture
def pty_stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Monkeypatch every syscall the PTY path touches.

    Returns a dict of the stubs the tests want to inspect. The shuttle
    thread is replaced with `_StubThread` so nothing runs in the
    background, and `signal.signal` is routed through a recorder that
    still honours `restore` semantics during teardown.

    All patches target string paths through `manicure.supervisor.*` so
    mypy's `--no-implicit-reexport` stays quiet (module-attr access on
    re-exported stdlib modules would trip the attr-defined check).
    """
    import os as _os
    import signal as _signal
    from unittest.mock import MagicMock

    _StubThread.instances.clear()

    openpty = MagicMock(return_value=(77, 88))
    monkeypatch.setattr("manicure.supervisor.pty.openpty", openpty)

    # Winsize is an opaque 8-byte blob; any stable value works.
    winsize_bytes = b"\x18\x00\x50\x00\x00\x00\x00\x00"
    ioctl = MagicMock(return_value=winsize_bytes)
    monkeypatch.setattr("manicure.supervisor.fcntl.ioctl", ioctl)

    old_attrs: list[Any] = [
        termios.ICRNL,
        1,
        2,
        termios.ECHO | termios.ICANON | termios.ISIG,
        4,
        5,
        [b"?"] * 32,
    ]
    tcgetattr = MagicMock(return_value=old_attrs)
    tcsetattr = MagicMock()
    monkeypatch.setattr("manicure.supervisor.termios.tcgetattr", tcgetattr)
    monkeypatch.setattr("manicure.supervisor.termios.tcsetattr", tcsetattr)

    isatty = MagicMock(return_value=True)
    monkeypatch.setattr("manicure.supervisor.os.isatty", isatty)

    close_calls: list[int] = []
    real_close = _os.close

    def _recording_close(fd: int) -> None:
        close_calls.append(fd)
        # The slave/master FDs we hand out (88, 77) are fakes — don't
        # call the real close on them. Real fds (log files) still go
        # through the real syscall.
        if fd in (77, 88):
            return
        real_close(fd)

    monkeypatch.setattr("manicure.supervisor.os.close", _recording_close)

    signal_calls: list[tuple[int, Any]] = []
    prev_handlers: dict[int, Any] = {}
    real_signal = _signal.signal
    sentinel_prev = object()

    def _recording_signal(signum: int, handler: Any) -> Any:
        signal_calls.append((signum, handler))
        if signum == _signal.SIGWINCH:
            prev = prev_handlers.get(signum, sentinel_prev)
            prev_handlers[signum] = handler
            return prev
        return real_signal(signum, handler)

    monkeypatch.setattr("manicure.supervisor.signal.signal", _recording_signal)

    monkeypatch.setattr("manicure.supervisor.threading.Thread", _StubThread)

    # Ensure sys.stdin/stdout .fileno() return known values regardless
    # of the pytest capture state. 0/1 are the real POSIX values and
    # are what the rest of the stubs assume.
    monkeypatch.setattr("manicure.supervisor.sys.stdin", _FakeStdin(fileno=0))
    monkeypatch.setattr("manicure.supervisor.sys.stdout", _FakeStdin(fileno=1))

    return {
        "openpty": openpty,
        "ioctl": ioctl,
        "winsize_bytes": winsize_bytes,
        "tcgetattr": tcgetattr,
        "tcsetattr": tcsetattr,
        "isatty": isatty,
        "close_calls": close_calls,
        "signal_calls": signal_calls,
        "old_attrs": old_attrs,
        "sentinel_prev": sentinel_prev,
    }


class _FakeStdin:
    """Minimal stand-in for `sys.stdin` that exposes `fileno()`."""

    def __init__(self, fileno: int) -> None:
        self._fileno = fileno

    def fileno(self) -> int:
        return self._fileno


def test_spawn_pty_opens_pty_and_wires_slave_to_popen(
    patched_popen: type[FakePopen],
    pty_stubs: dict[str, Any],
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)

    assert pty_stubs["openpty"].call_count == 1
    fp = _as_fake(mp)
    # Slave side is 88 per the openpty stub; it must be wired into
    # every stdio slot, with start_new_session so the child gets its
    # own session and controlling tty.
    assert fp.stdin == 88
    assert fp.stdout == 88
    assert fp.stderr == 88
    # `start_new_session=True` lands in the **kwargs catch-all on
    # FakePopen; re-spy via the instance's construction args would
    # require extending the stub. Instead assert the master fd
    # survived on the managed process — a proxy for the PTY path
    # having succeeded.
    assert mp.master_fd == 77


def test_spawn_pty_start_new_session_is_true(
    monkeypatch: pytest.MonkeyPatch,
    pty_stubs: dict[str, Any],
) -> None:
    """Capture kwargs on Popen explicitly so we can assert
    `start_new_session=True` made it through."""
    captured: dict[str, Any] = {}

    class CapturingFakePopen(FakePopen):
        def __init__(
            self,
            argv: list[str],
            **kwargs: Any,
        ) -> None:
            captured.update(kwargs)
            super().__init__(argv, **kwargs)

    monkeypatch.setattr("manicure.supervisor.subprocess.Popen", CapturingFakePopen)

    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)

    assert captured.get("start_new_session") is True
    assert mp.process_group == _as_fake(mp).pid


def test_spawn_pty_propagates_parent_winsize(
    patched_popen: type[FakePopen],
    pty_stubs: dict[str, Any],
) -> None:
    import termios as _termios

    sup = ProcessSupervisor()
    sup.spawn("claude", ["claude"], foreground=True, pty=True)

    ioctl = pty_stubs["ioctl"]
    # Two ioctl calls: TIOCGWINSZ on parent stdin, TIOCSWINSZ on slave.
    assert ioctl.call_count >= 2
    setwinsz_call = ioctl.call_args_list[1]
    # (slave_fd, TIOCSWINSZ, winsize_bytes) — the winsize we read from
    # the parent is propagated verbatim to the child's slave side.
    assert setwinsz_call.args[0] == 88  # slave_fd
    assert setwinsz_call.args[1] == _termios.TIOCSWINSZ
    assert setwinsz_call.args[2] == pty_stubs["winsize_bytes"]


def test_spawn_pty_installs_cbreak_without_icrnl(
    patched_popen: type[FakePopen],
    pty_stubs: dict[str, Any],
) -> None:
    """Keep cbreak semantics but pass Return through as ``\\r``."""
    sup = ProcessSupervisor()
    sup.spawn("claude", ["claude"], foreground=True, pty=True)
    call = pty_stubs["tcsetattr"].call_args_list[0]
    new_attrs = call.args[2]

    assert call.args[0] == 0
    assert call.args[1] == termios.TCSAFLUSH
    assert not (new_attrs[tty.IFLAG] & termios.ICRNL)
    assert not (new_attrs[tty.LFLAG] & termios.ECHO)
    assert not (new_attrs[tty.LFLAG] & termios.ICANON)
    assert new_attrs[tty.LFLAG] & termios.ISIG


def test_spawn_pty_falls_back_when_parent_not_tty(
    patched_popen: type[FakePopen],
    pty_stubs: dict[str, Any],
) -> None:
    import warnings as _warnings

    pty_stubs["isatty"].return_value = False

    sup = ProcessSupervisor()
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)

    runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert len(runtime) == 1
    assert "not a tty" in str(runtime[0].message)

    fp = _as_fake(mp)
    assert fp.stdin is None
    assert fp.stdout is None
    assert fp.stderr is None
    # No PTY resources should be attached.
    assert mp.master_fd is None
    assert mp.stop_event is None
    assert mp.shuttle_thread is None
    pty_stubs["openpty"].assert_not_called()


def test_spawn_pty_restores_terminal_on_popen_failure(
    monkeypatch: pytest.MonkeyPatch,
    pty_stubs: dict[str, Any],
) -> None:
    class BoomPopen(FakePopen):
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            raise OSError("boom")

    monkeypatch.setattr("manicure.supervisor.subprocess.Popen", BoomPopen)

    sup = ProcessSupervisor()
    with pytest.raises(OSError, match="boom"):
        sup.spawn("claude", ["claude"], foreground=True, pty=True)

    restore_call = pty_stubs["tcsetattr"].call_args_list[-1]
    assert restore_call.args == (0, termios.TCSADRAIN, pty_stubs["old_attrs"])
    assert 88 in pty_stubs["close_calls"]
    assert 77 in pty_stubs["close_calls"]


def test_spawn_pty_kills_child_if_post_exec_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
    patched_popen: type[FakePopen],
    pty_stubs: dict[str, Any],
) -> None:
    def _boom_signal(signum: int, handler: Any) -> Any:
        if signum == signal.SIGWINCH:
            raise OSError("boom")
        return signal.signal(signum, handler)

    monkeypatch.setattr("manicure.supervisor.signal.signal", _boom_signal)

    sup = ProcessSupervisor()
    with pytest.raises(OSError, match="boom"):
        sup.spawn("claude", ["claude"], foreground=True, pty=True)

    assert len(FakePopen.instances) == 1
    fp = FakePopen.instances[0]
    assert FakePopen.killpg_calls == [(fp.pid, int(signal.SIGKILL))]
    assert fp.returncode == -int(signal.SIGKILL)
    restore_call = pty_stubs["tcsetattr"].call_args_list[-1]
    assert restore_call.args == (0, termios.TCSADRAIN, pty_stubs["old_attrs"])


def test_spawn_pty_requires_foreground(patched_popen: type[FakePopen]) -> None:
    sup = ProcessSupervisor()
    with pytest.raises(ValueError, match="requires `foreground=True`"):
        sup.spawn("claude", ["claude"], pty=True)


def test_spawn_pty_rejects_log_path(
    patched_popen: type[FakePopen], tmp_log: Path
) -> None:
    """log_path + pty is caught by the foreground/log-path mutex; the
    explicit pty+log combo is belt-and-suspenders for a precise message."""
    sup = ProcessSupervisor()
    with pytest.raises(ValueError, match="mutually exclusive|`pty=True`"):
        sup.spawn(
            "claude",
            ["claude"],
            foreground=True,
            pty=True,
            log_path=tmp_log,
        )


def test_spawn_pty_records_managed_process_state(
    patched_popen: type[FakePopen],
    pty_stubs: dict[str, Any],
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)

    assert mp.master_fd == 77
    assert mp.stop_event is not None
    assert mp.shuttle_thread is not None
    assert mp.old_termios_attrs == pty_stubs["old_attrs"]
    # Previous SIGWINCH handler recorded — first install returns the
    # fixture's sentinel because no handler was registered before.
    assert mp.prev_sigwinch_handler is pty_stubs["sentinel_prev"]
    # Shuttle thread was started but (since `_StubThread` fakes it)
    # no target ran.
    assert len(_StubThread.instances) == 1
    assert _StubThread.instances[0].started is True
    assert _StubThread.instances[0].daemon is True


def test_terminate_all_tears_down_pty_resources(
    patched_popen: type[FakePopen],
    pty_stubs: dict[str, Any],
) -> None:
    import termios as _termios

    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)
    _as_fake(mp)._die_on_terminate = True

    # Capture pre-teardown references — the fields will be cleared.
    stop_event = mp.stop_event
    shuttle_thread = mp.shuttle_thread
    assert stop_event is not None
    assert isinstance(shuttle_thread, _StubThread)  # narrows for mypy

    pty_stubs["close_calls"].clear()

    sup.terminate_all(grace_seconds=0.01)

    assert FakePopen.killpg_calls == [(mp.popen.pid, int(signal.SIGTERM))]

    # Stop event set, thread joined.
    assert stop_event.is_set()
    assert shuttle_thread.join_calls, "shuttle thread should have been joined"
    # termios restored to the saved attrs with TCSADRAIN.
    assert pty_stubs["tcsetattr"].called
    call = pty_stubs["tcsetattr"].call_args

    assert call.args[0] == 0  # stdin fd
    assert call.args[1] == _termios.TCSADRAIN
    assert call.args[2] == pty_stubs["old_attrs"]
    # master_fd (77) closed.
    assert 77 in pty_stubs["close_calls"]
    # SIGWINCH handler restored — should see a `signal.signal(SIGWINCH, ...)`
    # call during teardown with the previously-saved handler (sentinel).
    restore_calls = [
        h for sig, h in pty_stubs["signal_calls"] if sig == signal.SIGWINCH
    ]
    assert pty_stubs["sentinel_prev"] in restore_calls
    # Managed process fields cleared so a second teardown is a no-op.
    assert mp.master_fd is None
    assert mp.shuttle_thread is None
    assert mp.old_termios_attrs is None
    assert mp.prev_sigwinch_handler is None


def test_signal_child_forwards_arbitrary_signal_to_pid(
    patched_popen: type[FakePopen],
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True)

    sup._signal_child(mp, signal.SIGHUP)

    assert FakePopen.kill_calls_by_pid == [(mp.popen.pid, int(signal.SIGHUP))]
    assert _as_fake(mp).returncode == -int(signal.SIGHUP)


def test_terminate_all_pty_teardown_is_idempotent(
    patched_popen: type[FakePopen],
    pty_stubs: dict[str, Any],
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)
    _as_fake(mp)._die_on_terminate = True

    sup.terminate_all(grace_seconds=0.01)
    # Second pass should not raise (no double-close, no double-restore).
    sup.terminate_all(grace_seconds=0.01)


def test_pty_shuttle_forwards_both_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct unit test of `_pty_shuttle` — exercises the forwarding
    logic with mocked `os.read`/`os.write`/`select.select`.

    Child output must land on ``stdout_fd`` (fd 1), NOT back on
    ``stdin_fd`` (fd 0). Writing to fd 0 happens to work on shells
    that dup it from an ``O_RDWR`` /dev/tty handle, but breaks under
    any harness that opens stdin ``O_RDONLY``.
    """
    import threading as _threading

    from manicure.supervisor import _pty_shuttle

    stdin_fd = 0
    stdout_fd = 1
    master_fd = 77
    stop_event = _threading.Event()

    # Script the select/read sequence: first tick reads from stdin,
    # second tick reads from master, third tick trips the stop event.
    select_calls: list[tuple[list[int], list[int], list[int], float]] = []

    def _fake_select(
        rlist: list[int], wlist: list[int], xlist: list[int], timeout: float
    ) -> tuple[list[int], list[int], list[int]]:
        select_calls.append((rlist, wlist, xlist, timeout))
        if len(select_calls) == 1:
            return [stdin_fd], [], []
        if len(select_calls) == 2:
            return [master_fd], [], []
        stop_event.set()
        return [], [], []

    monkeypatch.setattr("manicure.supervisor.select.select", _fake_select)

    reads: dict[int, bytes] = {stdin_fd: b"keystroke", master_fd: b"echo"}

    def _fake_read(fd: int, _n: int) -> bytes:
        return reads[fd]

    writes: list[tuple[int, bytes]] = []

    def _fake_write(fd: int, data: bytes) -> int:
        writes.append((fd, data))
        return len(data)

    monkeypatch.setattr("manicure.supervisor.os.read", _fake_read)
    monkeypatch.setattr("manicure.supervisor.os.write", _fake_write)

    _pty_shuttle(stdin_fd, stdout_fd, master_fd, stop_event)

    # Keystrokes go to master; child output goes to stdout (fd 1) and
    # must NOT come back through fd 0.
    assert (master_fd, b"keystroke") in writes
    assert (stdout_fd, b"echo") in writes
    assert (stdin_fd, b"echo") not in writes
    assert stop_event.is_set()


def test_pty_shuttle_exits_on_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shuttle must exit quickly when the stop event is set, even
    if select itself returns empty (no pending IO)."""
    import threading as _threading

    from manicure.supervisor import _pty_shuttle

    stop_event = _threading.Event()
    select_calls = 0

    def _fake_select(
        _r: list[int], _w: list[int], _x: list[int], _t: float
    ) -> tuple[list[int], list[int], list[int]]:
        nonlocal select_calls
        select_calls += 1
        if select_calls == 1:
            stop_event.set()
        return [], [], []

    monkeypatch.setattr("manicure.supervisor.select.select", _fake_select)
    # os.read/write must not be called on this path.
    monkeypatch.setattr(
        "manicure.supervisor.os.read",
        lambda *_a: pytest.fail("shuttle read() with stop event set"),
    )

    _pty_shuttle(0, 1, 77, stop_event)
    assert stop_event.is_set()


def test_parent_cbreak_preserves_return_for_raw_child() -> None:
    """Return must cross the PTY bridge as ``\\r``, not be rewritten to ``\\n``."""
    import os
    import pty

    from manicure.supervisor import _install_parent_cbreak

    parent_master, parent_slave = pty.openpty()
    child_master, child_slave = pty.openpty()
    parent_old: list[Any] | None = None
    child_old: list[Any] | None = None
    try:
        parent_old = _install_parent_cbreak(parent_slave)

        child_old = termios.tcgetattr(child_slave)
        child_new = list(child_old)
        child_new[tty.IFLAG] &= ~termios.ICRNL
        child_new[tty.LFLAG] &= ~(termios.ECHO | termios.ICANON)
        child_new[tty.CC] = list(child_new[tty.CC])
        child_new[tty.CC][termios.VMIN] = 1
        child_new[tty.CC][termios.VTIME] = 0
        termios.tcsetattr(child_slave, termios.TCSANOW, child_new)

        os.write(parent_master, b"\r")
        forwarded = os.read(parent_slave, 1)
        os.write(child_master, forwarded)
        child_seen = os.read(child_slave, 1)

        assert forwarded == b"\r"
        assert child_seen == b"\r"
    finally:
        if parent_old is not None:
            termios.tcsetattr(parent_slave, termios.TCSADRAIN, parent_old)
        if child_old is not None:
            termios.tcsetattr(child_slave, termios.TCSADRAIN, child_old)
        os.close(parent_master)
        os.close(parent_slave)
        os.close(child_master)
        os.close(child_slave)
