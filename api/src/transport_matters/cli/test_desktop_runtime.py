"""Tests for detached desktop runtime records."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from transport_matters.cli.desktop_runtime import (
    DesktopRuntimeRecord,
    desktop_log_path,
    desktop_record_path,
    desktop_runtime_dir,
    is_pid_alive,
    read_live_desktop_record,
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
