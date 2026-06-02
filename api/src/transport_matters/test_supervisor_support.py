"""Shared test support for `transport_matters.supervisor`."""

import signal
import subprocess
import termios
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from transport_matters.supervisor import ManagedProcess


class FakePopen:
    """Stand-in for `subprocess.Popen` that never forks a real process."""

    instances: ClassVar[list[FakePopen]] = []
    killpg_calls: ClassVar[list[tuple[int, int]]] = []
    kill_calls_by_pid: ClassVar[list[tuple[int, int]]] = []
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
def reset_fake_popen_registry() -> Iterator[None]:
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

    monkeypatch.setattr("transport_matters.supervisor.subprocess.Popen", FakePopen)
    monkeypatch.setattr("transport_matters.supervisor.os.killpg", _fake_killpg)
    monkeypatch.setattr("transport_matters.supervisor.os.kill", _fake_kill)
    return FakePopen


@pytest.fixture
def tmp_log(tmp_path: Path) -> Path:
    """A path inside `tmp_path` suitable for log-redirect tests."""
    return tmp_path / "child.log"


def as_fake(mp: ManagedProcess) -> FakePopen:
    """Narrow `mp.popen` to `FakePopen` for test assertions."""
    assert isinstance(mp.popen, FakePopen)
    return mp.popen


class StubThread:
    """Stand-in for `threading.Thread` used in the PTY shuttle tests."""

    instances: ClassVar[list[StubThread]] = []

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
        StubThread.instances.append(self)

    def start(self) -> None:
        self.started = True

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)


@pytest.fixture
def pty_stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Monkeypatch every syscall the PTY path touches."""
    import os as _os
    import signal as _signal
    from unittest.mock import MagicMock

    StubThread.instances.clear()

    openpty = MagicMock(return_value=(77, 88))
    monkeypatch.setattr("transport_matters.supervisor.pty.openpty", openpty)

    winsize_bytes = b"\x18\x00\x50\x00\x00\x00\x00\x00"
    ioctl = MagicMock(return_value=winsize_bytes)
    monkeypatch.setattr("transport_matters.supervisor.fcntl.ioctl", ioctl)

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
    monkeypatch.setattr("transport_matters.supervisor.termios.tcgetattr", tcgetattr)
    monkeypatch.setattr("transport_matters.supervisor.termios.tcsetattr", tcsetattr)

    isatty = MagicMock(return_value=True)
    monkeypatch.setattr("transport_matters.supervisor.os.isatty", isatty)

    close_calls: list[int] = []
    real_close = _os.close

    def _recording_close(fd: int) -> None:
        close_calls.append(fd)
        if fd in (77, 88):
            return
        real_close(fd)

    monkeypatch.setattr("transport_matters.supervisor.os.close", _recording_close)

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

    monkeypatch.setattr("transport_matters.supervisor.signal.signal", _recording_signal)
    monkeypatch.setattr("transport_matters.supervisor.threading.Thread", StubThread)
    monkeypatch.setattr("transport_matters.supervisor.sys.stdin", FakeStdio(fileno=0))
    monkeypatch.setattr("transport_matters.supervisor.sys.stdout", FakeStdio(fileno=1))

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


class FakeStdio:
    """Minimal stand-in for `sys.stdin` or `sys.stdout` that exposes `fileno()`."""

    def __init__(self, fileno: int) -> None:
        self._fileno = fileno

    def fileno(self) -> int:
        return self._fileno
