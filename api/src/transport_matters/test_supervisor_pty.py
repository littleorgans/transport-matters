"""PTY-specific tests for `transport_matters.supervisor`."""

from __future__ import annotations

import signal
import termios
import tty
from typing import TYPE_CHECKING, Any

import pytest

from transport_matters import test_supervisor_support as supervisor_support
from transport_matters.test_supervisor_support import StubThread, as_fake

pytest_plugins = ("transport_matters.test_supervisor_support",)
pytestmark = pytest.mark.usefixtures("patched_popen")

if TYPE_CHECKING:
    from pathlib import Path


def test_spawn_pty_opens_pty_and_wires_slave_to_popen(
    pty_stubs: dict[str, Any],
) -> None:
    from transport_matters.supervisor import ProcessSupervisor

    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)

    assert pty_stubs["openpty"].call_count == 1
    fp = as_fake(mp)
    assert fp.stdin == 88
    assert fp.stdout == 88
    assert fp.stderr == 88
    assert mp.master_fd == 77


def test_spawn_pty_start_new_session_is_true(
    monkeypatch: pytest.MonkeyPatch,
    pty_stubs: dict[str, Any],
) -> None:
    from transport_matters.supervisor import ProcessSupervisor

    captured: dict[str, Any] = {}

    class CapturingFakePopen(supervisor_support.FakePopen):
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            captured.update(kwargs)
            super().__init__(argv, **kwargs)

    monkeypatch.setattr(
        "transport_matters.supervisor.subprocess.Popen", CapturingFakePopen
    )

    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)

    assert captured.get("start_new_session") is True
    assert mp.process_group == as_fake(mp).pid


def test_spawn_pty_propagates_parent_winsize(pty_stubs: dict[str, Any]) -> None:
    import termios as _termios

    from transport_matters.supervisor import ProcessSupervisor

    sup = ProcessSupervisor()
    sup.spawn("claude", ["claude"], foreground=True, pty=True)

    ioctl = pty_stubs["ioctl"]
    assert ioctl.call_count >= 2
    setwinsz_call = ioctl.call_args_list[1]
    assert setwinsz_call.args[0] == 88
    assert setwinsz_call.args[1] == _termios.TIOCSWINSZ
    assert setwinsz_call.args[2] == pty_stubs["winsize_bytes"]


def test_spawn_pty_installs_cbreak_without_icrnl(pty_stubs: dict[str, Any]) -> None:
    from transport_matters.supervisor import ProcessSupervisor

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


def test_spawn_pty_falls_back_when_parent_not_tty(pty_stubs: dict[str, Any]) -> None:
    import warnings as _warnings

    from transport_matters.supervisor import ProcessSupervisor

    pty_stubs["isatty"].return_value = False

    sup = ProcessSupervisor()
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)

    runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert len(runtime) == 1
    assert "not a tty" in str(runtime[0].message)

    fp = as_fake(mp)
    assert fp.stdin is None
    assert fp.stdout is None
    assert fp.stderr is None
    assert mp.master_fd is None
    assert mp.stop_event is None
    assert mp.shuttle_thread is None
    pty_stubs["openpty"].assert_not_called()


def test_spawn_pty_restores_terminal_on_popen_failure(
    monkeypatch: pytest.MonkeyPatch,
    pty_stubs: dict[str, Any],
) -> None:
    from transport_matters.supervisor import ProcessSupervisor

    class BoomPopen(supervisor_support.FakePopen):
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            raise OSError("boom")

    monkeypatch.setattr("transport_matters.supervisor.subprocess.Popen", BoomPopen)

    sup = ProcessSupervisor()
    with pytest.raises(OSError, match="boom"):
        sup.spawn("claude", ["claude"], foreground=True, pty=True)

    restore_call = pty_stubs["tcsetattr"].call_args_list[-1]
    assert restore_call.args == (0, termios.TCSADRAIN, pty_stubs["old_attrs"])
    assert 88 in pty_stubs["close_calls"]
    assert 77 in pty_stubs["close_calls"]


def test_spawn_pty_kills_child_if_post_exec_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
    pty_stubs: dict[str, Any],
) -> None:
    from transport_matters.supervisor import ProcessSupervisor

    def _boom_signal(signum: int, handler: Any) -> Any:
        if signum == signal.SIGWINCH:
            raise OSError("boom")
        return signal.signal(signum, handler)

    monkeypatch.setattr("transport_matters.supervisor.signal.signal", _boom_signal)

    sup = ProcessSupervisor()
    with pytest.raises(OSError, match="boom"):
        sup.spawn("claude", ["claude"], foreground=True, pty=True)

    assert len(supervisor_support.FakePopen.instances) == 1
    fp = supervisor_support.FakePopen.instances[0]
    assert supervisor_support.FakePopen.killpg_calls == [(fp.pid, int(signal.SIGKILL))]
    assert fp.returncode == -int(signal.SIGKILL)
    restore_call = pty_stubs["tcsetattr"].call_args_list[-1]
    assert restore_call.args == (0, termios.TCSADRAIN, pty_stubs["old_attrs"])


def test_spawn_pty_requires_foreground() -> None:
    from transport_matters.supervisor import ProcessSupervisor

    sup = ProcessSupervisor()
    with pytest.raises(ValueError, match="requires `foreground=True`"):
        sup.spawn("claude", ["claude"], pty=True)


def test_spawn_pty_rejects_log_path(tmp_log: Path) -> None:
    from transport_matters.supervisor import ProcessSupervisor

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
    pty_stubs: dict[str, Any],
) -> None:
    from transport_matters.supervisor import ProcessSupervisor

    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)

    assert mp.master_fd == 77
    assert mp.stop_event is not None
    assert mp.shuttle_thread is not None
    assert mp.old_termios_attrs == pty_stubs["old_attrs"]
    assert mp.prev_sigwinch_handler is pty_stubs["sentinel_prev"]
    assert len(StubThread.instances) == 1
    assert StubThread.instances[0].started is True
    assert StubThread.instances[0].daemon is True


def test_pty_shuttle_forwards_both_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading as _threading

    from transport_matters.supervisor import _pty_shuttle

    stdin_fd = 0
    stdout_fd = 1
    master_fd = 77
    stop_event = _threading.Event()

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

    monkeypatch.setattr("transport_matters.supervisor.select.select", _fake_select)

    reads: dict[int, bytes] = {stdin_fd: b"keystroke", master_fd: b"echo"}

    def _fake_read(fd: int, _n: int) -> bytes:
        return reads[fd]

    writes: list[tuple[int, bytes]] = []

    def _fake_write(fd: int, data: bytes) -> int:
        writes.append((fd, data))
        return len(data)

    monkeypatch.setattr("transport_matters.supervisor.os.read", _fake_read)
    monkeypatch.setattr("transport_matters.supervisor.os.write", _fake_write)

    _pty_shuttle(stdin_fd, stdout_fd, master_fd, stop_event)

    assert (master_fd, b"keystroke") in writes
    assert (stdout_fd, b"echo") in writes
    assert (stdin_fd, b"echo") not in writes
    assert stop_event.is_set()


def test_pty_shuttle_exits_on_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading as _threading

    from transport_matters.supervisor import _pty_shuttle

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

    monkeypatch.setattr("transport_matters.supervisor.select.select", _fake_select)
    monkeypatch.setattr(
        "transport_matters.supervisor.os.read",
        lambda *_a: pytest.fail("shuttle read() with stop event set"),
    )

    _pty_shuttle(0, 1, 77, stop_event)
    assert stop_event.is_set()


def test_parent_cbreak_preserves_return_for_raw_child() -> None:
    import os
    import pty

    from transport_matters.supervisor import _install_parent_cbreak

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
