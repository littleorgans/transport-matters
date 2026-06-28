"""Tests for detached desktop runtime records."""

from __future__ import annotations

import json
import os
import re
import signal
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from transport_matters.cli.desktop_runtime import (
    DesktopHealthProbeResult,
    DesktopLivenessPolicy,
    DesktopRuntimeDiscoveryError,
    DesktopRuntimeRecord,
    StopDesktopResult,
    desktop_log_path,
    desktop_record_path,
    desktop_runtime_dir,
    desktop_runtime_status_to_json,
    discover_desktop_runtime,
    is_pid_alive,
    read_live_desktop_record,
    stop_desktop_record,
    write_desktop_record,
)

from ._helpers import _write_desktop_record

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
        cwd=str(tmp_path / "workspace"),
        storage_dir=str(tmp_path),
        version="1.2.3",
    )

    write_desktop_record(record_file, record)

    loaded = read_live_desktop_record(record_file, pid_alive=lambda pid: pid == 1234)
    assert loaded == record
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", loaded.started_at)
    assert not list(record_file.parent.glob(".*.tmp"))


def test_read_live_desktop_record_accepts_v1_record(tmp_path: Path) -> None:
    record_file = desktop_record_path(tmp_path)
    record_file.parent.mkdir(parents=True)
    record_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "channel": "preview",
                "pid": 1234,
                "proxy_port": 8797,
                "web_port": 8798,
                "log_path": str(desktop_log_path(tmp_path)),
                "started_at": "2026-06-23T07:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    loaded = read_live_desktop_record(record_file, pid_alive=lambda pid: pid == 1234)

    assert loaded == DesktopRuntimeRecord(
        channel="preview",
        pid=1234,
        proxy_port=8797,
        web_port=8798,
        log_path=str(desktop_log_path(tmp_path)),
        started_at="2026-06-23T07:00:00Z",
    )
    assert loaded.instance == "channel"
    assert loaded.version is None


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
            cwd=str(tmp_path / "workspace"),
            storage_dir=str(tmp_path),
            version="1.2.3",
        ),
    )

    assert read_live_desktop_record(record_file, pid_alive=lambda _pid: False) is None
    assert not record_file.exists()


def test_read_live_desktop_record_rejects_malformed_payloads(tmp_path: Path) -> None:
    record_file = desktop_record_path(tmp_path)
    record_file.parent.mkdir(parents=True)
    record_file.write_text('{"schema_version":1,"pid":1234}', encoding="utf-8")

    assert read_live_desktop_record(record_file, pid_alive=lambda _pid: True) is None


def test_discover_desktop_runtime_returns_absent_status(tmp_path: Path) -> None:
    status = discover_desktop_runtime(
        channel="preview",
        storage_dir=tmp_path,
        route="canvas",
        cwd=tmp_path / "workspace",
        health_timeout_ms=0,
    )

    assert desktop_runtime_status_to_json(status) == {
        "runtime": {
            "schemaVersion": 2,
            "state": "absent",
            "channel": "preview",
            "instance": "channel",
            "pid": None,
            "proxyPort": None,
            "webPort": None,
            "apiBaseUrl": None,
            "healthUrl": None,
            "defaultRouteUrl": None,
            "cwd": None,
            "storageDir": str(tmp_path.resolve()),
            "recordPath": str(desktop_record_path(tmp_path.resolve())),
            "logPath": None,
            "startedAt": None,
            "version": None,
        }
    }


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("{", "invalid_json"),
        ('{"schema_version":99}', "invalid_record"),
    ],
)
def test_discover_desktop_runtime_raises_invalid_record(
    tmp_path: Path, payload: str, reason: str
) -> None:
    record_file = desktop_record_path(tmp_path)
    record_file.parent.mkdir(parents=True)
    record_file.write_text(payload, encoding="utf-8")

    with pytest.raises(DesktopRuntimeDiscoveryError) as exc_info:
        discover_desktop_runtime(
            channel="preview",
            storage_dir=tmp_path,
            route="canvas",
            cwd=tmp_path / "workspace",
            health_timeout_ms=0,
        )

    assert exc_info.value.code == "desktop_runtime_invalid"
    assert exc_info.value.details is not None
    assert exc_info.value.details["reason"] == reason
    assert not record_file.exists()


def test_discover_desktop_runtime_unlinks_stale_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_file = _write_preview_record(tmp_path, pid=1234)
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: False)

    status = discover_desktop_runtime(
        channel="preview",
        storage_dir=tmp_path,
        route="canvas",
        cwd=tmp_path / "workspace",
    )

    payload = desktop_runtime_status_to_json(status)["runtime"]
    assert payload["state"] == "stale"
    assert payload["reason"] == "pid_not_running"
    assert payload["pid"] == 1234
    assert not record_file.exists()


def test_discover_desktop_runtime_reports_unhealthy_when_health_probe_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_preview_record(tmp_path, pid=1234)
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: DesktopHealthProbeResult(status="failed"),
    )

    status = discover_desktop_runtime(
        channel="preview",
        storage_dir=tmp_path,
        route="canvas",
        cwd=tmp_path / "workspace",
    )

    payload = desktop_runtime_status_to_json(status)["runtime"]
    assert payload["state"] == "unhealthy"
    assert payload["reason"] == "health_probe_failed"
    assert payload["webPort"] == 8798


def test_discover_desktop_runtime_reports_not_serving_after_refused_debounce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_preview_record(tmp_path, pid=1234)
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr("transport_matters.desktop_runtime.time.sleep", lambda _seconds: None)
    probes: list[tuple[int, float]] = []

    def refused_probe(web_port: int, *, timeout_s: float) -> DesktopHealthProbeResult:
        probes.append((web_port, timeout_s))
        return DesktopHealthProbeResult(status="refused")

    monkeypatch.setattr("transport_matters.desktop_runtime._probe_desktop_health", refused_probe)

    status = discover_desktop_runtime(
        channel="preview",
        storage_dir=tmp_path,
        route="canvas",
        cwd=tmp_path / "workspace",
        liveness_policy=DesktopLivenessPolicy(
            attempts=3,
            per_probe_timeout_s=2.0,
            backoff_s=0.01,
        ),
    )

    payload = desktop_runtime_status_to_json(status)["runtime"]
    assert payload["state"] == "not-serving"
    assert payload["reason"] == "health_probe_refused"
    assert probes == [(8798, 2.0), (8798, 2.0), (8798, 2.0)]


def test_discover_desktop_runtime_reports_wedged_after_timeout_debounce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_preview_record(tmp_path, pid=1234)
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr("transport_matters.desktop_runtime.time.sleep", lambda _seconds: None)

    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: DesktopHealthProbeResult(status="timeout"),
    )

    status = discover_desktop_runtime(
        channel="preview",
        storage_dir=tmp_path,
        route="canvas",
        cwd=tmp_path / "workspace",
        liveness_policy=DesktopLivenessPolicy(attempts=3),
    )

    payload = desktop_runtime_status_to_json(status)["runtime"]
    assert payload["state"] == "wedged"
    assert payload["reason"] == "health_probe_timeout"


def test_discover_desktop_runtime_reports_live_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_preview_record(tmp_path, pid=1234)
    live_workspace = tmp_path / "live-workspace"
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: DesktopHealthProbeResult(status="live"),
    )
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._read_runtime_meta",
        lambda *_args, **_kwargs: SimpleNamespace(channel="preview", cwd=str(live_workspace)),
    )

    status = discover_desktop_runtime(
        channel="preview",
        storage_dir=tmp_path,
        route="canvas",
        cwd=tmp_path / "workspace",
    )

    payload = desktop_runtime_status_to_json(status)["runtime"]
    assert payload["state"] == "live"
    assert payload["cwd"] == str(live_workspace.resolve())
    assert payload["apiBaseUrl"] == "http://127.0.0.1:8798"
    assert payload["healthUrl"] == "http://127.0.0.1:8798/health"
    assert str(payload["defaultRouteUrl"]).startswith("http://127.0.0.1:8798/canvas?")


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
    return _write_desktop_record(tmp_path, pid=pid)
