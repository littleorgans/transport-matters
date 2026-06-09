from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from transport_matters import config
from transport_matters.api.v1 import run_routes
from transport_matters.api.v1.test_terminal import _receive_until_disconnect, _wait_until
from transport_matters.main import create_app
from transport_matters.run_manager import RunState
from transport_matters.test_run_manager import (
    PreparedRunHarness,
    PtyHarness,
    make_manager,
    patch_pty_teardown,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

BACKEND_ORIGIN = "http://localhost:8788"


class ManagedRunHarness:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.pty = PtyHarness()
        patch_pty_teardown(monkeypatch, self.pty)
        self.prepared = PreparedRunHarness(tmp_path)
        self.manager = make_manager(tmp_path, self.pty, self.prepared)
        monkeypatch.setattr(run_routes, "create_run_manager", lambda: self.manager)


def test_post_get_attach_detach_and_delete(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        create_response = client.post(
            "/api/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        )
        assert create_response.status_code == 201
        run = create_response.json()["run"]
        assert run["viewerCount"] == 0
        assert run["state"] == "running"
        run_id = run["runId"]

        listed = client.get("/api/runs?cli=claude", headers=_http_headers(BACKEND_ORIGIN)).json()
        assert [item["runId"] for item in listed["runs"]] == [run_id]

        managed = harness.manager.get(run_id)
        harness.pty.write(managed.terminal, b"past")
        _wait_until(lambda: managed.scrollback.total_bytes >= len(b"past"))

        with client.websocket_connect(
            f"/api/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "run.terminal.ready"
            assert ready["run"]["viewerCount"] == 1
            assert ready["scrollback"]["replayedBytes"] == len(b"past")
            assert websocket.receive_bytes() == b"past"
            assert websocket.receive_json() == {"type": "run.terminal.scrollback-end"}
            harness.pty.write(managed.terminal, b"live")
            assert websocket.receive_bytes() == b"live"

        _wait_until(lambda: harness.manager.get(run_id).view().viewer_count == 0)
        still_running = client.get(
            f"/api/runs?state={RunState.RUNNING}",
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()
        assert [item["runId"] for item in still_running["runs"]] == [run_id]

        delete_response = client.delete(
            f"/api/runs/{run_id}",
            headers=_http_headers(BACKEND_ORIGIN),
        )
        assert delete_response.status_code == 200
        assert delete_response.json() == {
            "runId": run_id,
            "state": "exited",
            "stopReason": "explicit-stop",
        }


def test_post_rejects_origin_before_spawn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/api/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers("http://evil.test"),
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "origin_not_allowed"
    assert harness.manager.list() == []


def test_post_rejects_invalid_cwd_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/api/runs",
            json={"cli": "claude", "cwd": "relative/path"},
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_cwd"
    assert harness.manager.list() == []


def test_post_rejects_unsupported_cli_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/api/runs",
            json={"cli": "unknown", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_cli"
    assert harness.manager.list() == []


def test_delete_unknown_run_returns_machine_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.delete(
            "/api/runs/missing",
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "run_not_found"


def test_websocket_unknown_run_sends_error_and_closes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            "/api/runs/missing/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        assert websocket.receive_json() == {
            "type": "run.error",
            "code": "run_not_found",
            "message": "run not found: missing",
        }


def test_websocket_binary_input_reaches_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from transport_matters.api.v1.test_captured_terminal import (
        _python_client_argv,
        install_real_pty_manager,
    )

    manager, _lease = install_real_pty_manager(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv(
            "import sys\n"
            "data = sys.stdin.buffer.readline()\n"
            "sys.stdout.buffer.write(b'ECHO:' + data)\n"
            "sys.stdout.flush()\n"
        ),
    )
    client = _client(monkeypatch, tmp_path)

    with client:
        run_id = client.post(
            "/api/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        with client.websocket_connect(
            f"/api/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            assert websocket.receive_json()["type"] == "run.terminal.ready"
            assert websocket.receive_json() == {"type": "run.terminal.scrollback-end"}
            websocket.send_bytes(b"ping\n")
            output = _receive_until_disconnect(websocket, needle=b"ECHO:ping")

    assert b"ECHO:ping" in output
    assert manager.get(run_id).state is RunState.EXITED


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    config.get_settings.cache_clear()
    return TestClient(create_app())


def _http_headers(origin: str, *, host: str = "localhost:8788") -> dict[str, str]:
    return {"origin": origin, "host": host}


def _websocket_headers(origin: str, *, host: str = "localhost:8788") -> dict[str, str]:
    return {"origin": origin, "host": host}
