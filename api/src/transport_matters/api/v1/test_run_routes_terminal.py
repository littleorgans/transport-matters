from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from transport_matters.api.v1 import terminal_bridge
from transport_matters.api.v1.test_run_routes import (
    BACKEND_ORIGIN,
    ManagedRunHarness,
    _client,
    _http_headers,
    _websocket_headers,
)
from transport_matters.api.v1.test_terminal import _wait_until
from transport_matters.run_manager import RunState

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_websocket_unknown_run_sends_error_and_closes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            "/v1/runs/missing/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        assert websocket.receive_json() == {
            "type": "run.error",
            "code": "run_not_found",
            "message": "run not found: missing",
        }


def test_websocket_terminated_run_sends_typed_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        run_id = client.post(
            "/v1/runs",
            json={"harness": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        client.post(f"/v1/runs/{run_id}/terminate", headers=_http_headers(BACKEND_ORIGIN))
        with client.websocket_connect(
            f"/v1/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            assert websocket.receive_json()["code"] == "run_terminated"


def test_websocket_stale_run_sends_typed_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        run_id = client.post(
            "/v1/runs",
            json={"harness": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        attached = asyncio.run(harness.manager.attach(run_id, cols=80, rows=24))
        harness.manager.detach(run_id, attached.attachment.attachment_id)
        terminal = harness.manager.get(run_id).terminal
        assert terminal is not None
        harness.pty.close_master(terminal)
        with client.websocket_connect(
            f"/v1/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            assert websocket.receive_json()["code"] == "run_stale"


def test_websocket_escape_interrupt_byte_reaches_child_without_terminating_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    writes: list[bytes] = []

    def capture_write_all(_fd: int, payload: bytes) -> None:
        writes.append(payload)

    monkeypatch.setattr(terminal_bridge, "write_all", capture_write_all)
    client = _client(monkeypatch, tmp_path)

    with client:
        run_id = client.post(
            "/v1/runs",
            json={"harness": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        with client.websocket_connect(
            f"/v1/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            assert websocket.receive_json()["type"] == "run.terminal.ready"
            assert websocket.receive_json() == {"type": "run.terminal.scrollback-end"}
            websocket.send_bytes(b"\x1b")
            _wait_until(lambda: writes == [b"\x1b"])
            assert harness.manager.get(run_id).state is RunState.RUNNING
        client.post(f"/v1/runs/{run_id}/terminate", headers=_http_headers(BACKEND_ORIGIN))
