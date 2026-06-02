"""Wait and poll tests for `transport_matters.supervisor`."""

from typing import TYPE_CHECKING

import pytest

from transport_matters.supervisor import SIGNAL_EXIT, ProcessSupervisor

pytest_plugins = ("transport_matters.test_supervisor_support",)
pytestmark = pytest.mark.usefixtures("patched_popen")

if TYPE_CHECKING:
    from pathlib import Path


def test_poll_any_returns_none_when_all_live(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    sup.spawn("claude", ["claude"], foreground=True)
    assert sup.poll_any() is None


def test_poll_any_returns_exited_child(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp = sup.spawn("claude", ["claude"], foreground=True)
    mp.popen.returncode = 7
    result = sup.poll_any()
    assert result == ("claude", 7)


def test_wait_any_returns_first_exited(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    mp_mitm = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    sup.spawn("claude", ["claude"], foreground=True)
    mp_mitm.popen.returncode = 1
    assert sup.wait_any(poll_interval=0.001) == ("mitmdump", 1)


def test_wait_any_returns_signal_sentinel(tmp_log: Path) -> None:
    import signal

    sup = ProcessSupervisor()
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    sup._on_signal(signal.SIGINT, None)
    name, rc = sup.wait_any(poll_interval=0.001)
    assert name == SIGNAL_EXIT
    assert rc == int(signal.SIGINT)


def test_wait_any_prefers_child_exit_over_signal(tmp_log: Path) -> None:
    import signal

    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp.popen.returncode = 0
    sup._on_signal(signal.SIGINT, None)
    name, rc = sup.wait_any(poll_interval=0.001)
    assert name == "mitmdump"
    assert rc == 0


def test_wait_one_ignores_other_children(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    mp_mitm = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    mp_cc = sup.spawn("claude", ["claude"], foreground=True)
    mp_mitm.popen.returncode = 0
    mp_cc.popen.returncode = 5
    assert sup.wait_one("claude", poll_interval=0.001) == ("claude", 5)


def test_wait_one_returns_signal_sentinel(tmp_log: Path) -> None:
    import signal

    sup = ProcessSupervisor()
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    sup._on_signal(signal.SIGTERM, None)
    name, rc = sup.wait_one("mitmdump", poll_interval=0.001)
    assert name == SIGNAL_EXIT
    assert rc == int(signal.SIGTERM)
