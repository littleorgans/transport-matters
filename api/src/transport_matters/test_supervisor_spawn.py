"""Spawn policy tests for `transport_matters.supervisor`."""

import subprocess
from typing import TYPE_CHECKING

import pytest

from transport_matters import test_supervisor_support as supervisor_support
from transport_matters.supervisor import ProcessSupervisor

pytest_plugins = ("transport_matters.test_supervisor_support",)
pytestmark = pytest.mark.usefixtures("patched_popen")

if TYPE_CHECKING:
    from pathlib import Path


def test_spawn_foreground_inherits_stdio() -> None:
    sup = ProcessSupervisor()
    sup.spawn("claude", ["claude"], foreground=True)

    assert len(supervisor_support.FakePopen.instances) == 1
    fp = supervisor_support.FakePopen.instances[0]
    assert fp.stdin is None
    assert fp.stdout is None
    assert fp.stderr is None


def test_spawn_background_redirects_to_log(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)

    fp = supervisor_support.FakePopen.instances[0]
    assert fp.stdin == subprocess.DEVNULL
    assert fp.stderr == subprocess.STDOUT
    assert isinstance(fp.stdout, int)
    assert fp.extra["start_new_session"] is True
    assert mp.process_group == fp.pid
    assert tmp_log.exists()


def test_spawn_rejects_both_foreground_and_log(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    with pytest.raises(ValueError, match="mutually exclusive"):
        sup.spawn("x", ["x"], foreground=True, log_path=tmp_log)


def test_spawn_rejects_neither_foreground_nor_log() -> None:
    sup = ProcessSupervisor()
    with pytest.raises(ValueError, match="foreground"):
        sup.spawn("x", ["x"])


def test_spawn_rejects_duplicate_live_name(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    with pytest.raises(RuntimeError, match="already running"):
        sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)


def test_spawn_allows_reuse_of_name_after_exit(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    first = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    first.popen.returncode = 0
    sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    assert len(supervisor_support.FakePopen.instances) == 2


def test_spawn_records_cwd_and_env(tmp_log: Path, tmp_path: Path) -> None:
    sup = ProcessSupervisor()
    sup.spawn(
        "mitmdump",
        ["mitmdump", "--foo"],
        env={"A": "1"},
        cwd=tmp_path,
        log_path=tmp_log,
    )
    fp = supervisor_support.FakePopen.instances[0]
    assert fp.argv == ["mitmdump", "--foo"]
    assert fp.env == {"A": "1"}
    assert fp.cwd == str(tmp_path)
