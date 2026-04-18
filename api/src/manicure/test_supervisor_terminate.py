"""Shutdown tests for `manicure.supervisor`."""

from __future__ import annotations

import signal
import warnings
from typing import TYPE_CHECKING, Any

import pytest

from manicure import test_supervisor_support as supervisor_support
from manicure.supervisor import ProcessSupervisor
from manicure.test_supervisor_support import StubThread, as_fake

pytest_plugins = ("manicure.test_supervisor_support",)
pytestmark = pytest.mark.usefixtures("patched_popen")

if TYPE_CHECKING:
    from pathlib import Path


def test_terminate_all_sends_sigterm_and_waits(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp.popen._die_on_terminate = True  # type: ignore[attr-defined]

    sup.terminate_all(grace_seconds=0.01)

    fake = as_fake(mp)
    assert supervisor_support.FakePopen.killpg_calls == [
        (fake.pid, int(signal.SIGTERM))
    ]
    assert fake.terminate_calls == 0
    assert fake.kill_calls == 0
    assert fake.returncode == 0


def test_terminate_all_escalates_to_sigkill(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp.popen._die_on_terminate = False  # type: ignore[attr-defined]
    mp.popen._die_on_kill = True  # type: ignore[attr-defined]

    sup.terminate_all(grace_seconds=0.01)

    fake = as_fake(mp)
    assert supervisor_support.FakePopen.killpg_calls == [
        (fake.pid, int(signal.SIGTERM)),
        (fake.pid, int(signal.SIGKILL)),
    ]
    assert fake.terminate_calls == 0
    assert fake.kill_calls == 0
    assert fake.returncode == -int(signal.SIGKILL)


def test_terminate_all_skips_already_dead(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp.popen.returncode = 0

    sup.terminate_all(grace_seconds=0.01)

    fake = as_fake(mp)
    assert supervisor_support.FakePopen.killpg_calls == []
    assert fake.terminate_calls == 0
    assert fake.kill_calls == 0


def test_terminate_all_is_idempotent(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp.popen._die_on_terminate = True  # type: ignore[attr-defined]

    sup.terminate_all(grace_seconds=0.01)
    sup.terminate_all(grace_seconds=0.01)

    fake = as_fake(mp)
    assert supervisor_support.FakePopen.killpg_calls == [
        (fake.pid, int(signal.SIGTERM))
    ]
    assert fake.terminate_calls == 0


def test_terminate_all_handles_multiple_children(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    mp_mitm = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp_cc = sup.spawn("claude", ["claude"], foreground=True)
    mp_mitm.popen._die_on_terminate = True  # type: ignore[attr-defined]
    mp_cc.popen._die_on_terminate = True  # type: ignore[attr-defined]

    sup.terminate_all(grace_seconds=0.01)

    assert supervisor_support.FakePopen.killpg_calls == [
        (mp_mitm.popen.pid, int(signal.SIGTERM))
    ]
    assert supervisor_support.FakePopen.kill_calls_by_pid == [
        (mp_cc.popen.pid, int(signal.SIGTERM))
    ]
    assert as_fake(mp_mitm).terminate_calls == 0
    assert as_fake(mp_cc).terminate_calls == 0


def test_terminate_all_warns_if_child_survives_sigkill(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
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


def test_signal_child_forwards_arbitrary_signal_to_pid() -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True)

    sup._signal_child(mp, signal.SIGHUP)

    assert supervisor_support.FakePopen.kill_calls_by_pid == [
        (mp.popen.pid, int(signal.SIGHUP))
    ]
    assert as_fake(mp).returncode == -int(signal.SIGHUP)


def test_terminate_all_tears_down_pty_resources(
    pty_stubs: dict[str, Any],
) -> None:
    import termios as _termios

    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)
    as_fake(mp)._die_on_terminate = True

    stop_event = mp.stop_event
    shuttle_thread = mp.shuttle_thread
    assert stop_event is not None
    assert isinstance(shuttle_thread, StubThread)

    pty_stubs["close_calls"].clear()

    sup.terminate_all(grace_seconds=0.01)

    assert supervisor_support.FakePopen.killpg_calls == [
        (mp.popen.pid, int(signal.SIGTERM))
    ]
    assert stop_event.is_set()
    assert shuttle_thread.join_calls
    assert pty_stubs["tcsetattr"].called
    call = pty_stubs["tcsetattr"].call_args

    assert call.args[0] == 0
    assert call.args[1] == _termios.TCSADRAIN
    assert call.args[2] == pty_stubs["old_attrs"]
    assert 77 in pty_stubs["close_calls"]
    restore_calls = [
        handler for sig, handler in pty_stubs["signal_calls"] if sig == signal.SIGWINCH
    ]
    assert pty_stubs["sentinel_prev"] in restore_calls
    assert mp.master_fd is None
    assert mp.shuttle_thread is None
    assert mp.old_termios_attrs is None
    assert mp.prev_sigwinch_handler is None


def test_terminate_all_pty_teardown_is_idempotent(
    pty_stubs: dict[str, Any],
) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("claude", ["claude"], foreground=True, pty=True)
    as_fake(mp)._die_on_terminate = True

    sup.terminate_all(grace_seconds=0.01)
    sup.terminate_all(grace_seconds=0.01)
