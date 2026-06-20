"""Tests for detached desktop runtime records."""

from __future__ import annotations

import os
import re
import signal
from typing import TYPE_CHECKING

from transport_matters.cli.desktop_runtime import (
    DesktopRuntimeRecord,
    StopDesktopResult,
    desktop_log_path,
    desktop_record_path,
    desktop_runtime_dir,
    is_pid_alive,
    read_live_desktop_record,
    stop_desktop_record,
    write_desktop_record,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_desktop_runtime_paths(tmp_path: Path) -> None:
    assert desktop_runtime_dir(tmp_path) == tmp_path / "runtime"
    assert desktop_record_path(tmp_path) == tmp_path / "runtime" / "desktop.json"
    assert desktop_log_path(tmp_path) == tmp_path / "runtime" / "desktop.log"


def test_desktop_record_write_is_atomic_json(tmp_path: Path) -> None:
    record_file = desktop_record_path(tmp_path)
    record = DesktopRuntimeRecord(
        channel="preview",
        pid=1234,
        proxy_port=8797,
        web_port=8798,
        log_path=str(desktop_log_path(tmp_path)),
    )

    write_desktop_record(record_file, record)

    loaded = read_live_desktop_record(record_file, pid_alive=lambda pid: pid == 1234)
    assert loaded == record
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", loaded.started_at)
    assert not list(record_file.parent.glob(".*.tmp"))


def test_is_pid_alive_reports_current_process_and_rejects_invalid_pid() -> None:
    assert is_pid_alive(os.getpid()) is True
    assert is_pid_alive(0) is False
    assert is_pid_alive(-1) is False


def test_read_live_desktop_record_unlinks_stale_record(tmp_path: Path) -> None:
    record_file = desktop_record_path(tmp_path)
    write_desktop_record(
        record_file,
        DesktopRuntimeRecord(
            channel="preview",
            pid=1234,
            proxy_port=8797,
            web_port=8798,
            log_path=str(desktop_log_path(tmp_path)),
        ),
    )

    assert read_live_desktop_record(record_file, pid_alive=lambda _pid: False) is None
    assert not record_file.exists()


def test_read_live_desktop_record_rejects_malformed_payloads(tmp_path: Path) -> None:
    record_file = desktop_record_path(tmp_path)
    record_file.parent.mkdir(parents=True)
    record_file.write_text('{"schema_version":1,"pid":1234}', encoding="utf-8")

    assert read_live_desktop_record(record_file, pid_alive=lambda _pid: True) is None


def test_stop_desktop_record_no_record_returns_nothing(tmp_path: Path) -> None:
    result = stop_desktop_record(desktop_record_path(tmp_path))

    assert result == StopDesktopResult(status="nothing")


def test_stop_desktop_record_malformed_json_unlinks_record(tmp_path: Path) -> None:
    record_file = desktop_record_path(tmp_path)
    record_file.parent.mkdir(parents=True)
    record_file.write_text("{", encoding="utf-8")

    result = stop_desktop_record(record_file)

    assert result == StopDesktopResult(status="nothing")
    assert not record_file.exists()


def test_stop_desktop_record_dead_pid_unlinks_stale_record(tmp_path: Path) -> None:
    record_file = _write_preview_record(tmp_path, pid=1234)

    result = stop_desktop_record(record_file, pid_alive=lambda _pid: False)

    assert result == StopDesktopResult(status="nothing")
    assert not record_file.exists()


def test_stop_desktop_record_sigterm_success_unlinks_record(tmp_path: Path) -> None:
    record_file = _write_preview_record(tmp_path, pid=1234)
    signals: list[int] = []
    alive_results = iter([True, False])

    def fake_kill(_pid: int, sig: int) -> None:
        signals.append(sig)

    result = stop_desktop_record(
        record_file,
        pid_alive=lambda _pid: next(alive_results),
        kill=fake_kill,
        sleep=lambda _seconds: None,
    )

    assert result == StopDesktopResult(status="stopped", pid=1234)
    assert signals == [signal.SIGTERM]
    assert not record_file.exists()


def test_stop_desktop_record_sigkill_fallback_after_timeout(tmp_path: Path) -> None:
    record_file = _write_preview_record(tmp_path, pid=1234)
    signals: list[int] = []
    sleeps: list[float] = []

    def fake_kill(_pid: int, sig: int) -> None:
        signals.append(sig)

    result = stop_desktop_record(
        record_file,
        timeout_s=0.2,
        poll_s=0.1,
        pid_alive=lambda _pid: True,
        kill=fake_kill,
        sleep=sleeps.append,
    )

    assert result == StopDesktopResult(status="stopped", pid=1234)
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert sleeps == [0.1, 0.1]
    assert not record_file.exists()


def test_stop_desktop_record_process_lookup_race_is_success(tmp_path: Path) -> None:
    record_file = _write_preview_record(tmp_path, pid=1234)

    def raise_process_lookup(_pid: int, _sig: int) -> None:
        raise ProcessLookupError

    result = stop_desktop_record(
        record_file,
        pid_alive=lambda _pid: True,
        kill=raise_process_lookup,
    )

    assert result == StopDesktopResult(status="stopped", pid=1234)
    assert not record_file.exists()


def test_stop_desktop_record_permission_error_bubbles(tmp_path: Path) -> None:
    record_file = _write_preview_record(tmp_path, pid=1234)

    def raise_permission(_pid: int, _sig: int) -> None:
        raise PermissionError

    try:
        stop_desktop_record(record_file, pid_alive=lambda _pid: True, kill=raise_permission)
    except PermissionError:
        pass
    else:
        raise AssertionError("PermissionError should bubble")

    assert record_file.exists()


def _write_preview_record(tmp_path: Path, *, pid: int) -> Path:
    record_file = desktop_record_path(tmp_path)
    write_desktop_record(
        record_file,
        DesktopRuntimeRecord(
            channel="preview",
            pid=pid,
            proxy_port=8797,
            web_port=8798,
            log_path=str(desktop_log_path(tmp_path)),
        ),
    )
    return record_file
