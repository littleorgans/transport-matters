from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, get_args

import pytest
from fastapi.testclient import TestClient

from transport_matters import config
from transport_matters.api.v1 import run_routes
from transport_matters.api.v1.test_terminal import _receive_until_disconnect, _wait_until
from transport_matters.captured_run import (
    CLAUDE_CLIENT_NAME,
    CapturedRunDependencies,
    CapturedRunLease,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.config import Settings
from transport_matters.main import create_app
from transport_matters.pty_session import TerminalPty, spawn_pty_process
from transport_matters.run_manager import RunManager, RunManagerErrorCode, RunState
from transport_matters.test_run_manager import (
    PreparedRunHarness,
    PtyHarness,
    make_manager,
    patch_pty_teardown,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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


def test_delete_run_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        run_id = client.post(
            "/api/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]

        first = client.delete(
            f"/api/runs/{run_id}",
            headers=_http_headers(BACKEND_ORIGIN),
        )
        second = client.delete(
            f"/api/runs/{run_id}",
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert harness.prepared.leases[0].close_count == 1


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


def test_websocket_stopped_run_sends_typed_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        run_id = client.post(
            "/api/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        client.delete(f"/api/runs/{run_id}", headers=_http_headers(BACKEND_ORIGIN))
        with client.websocket_connect(
            f"/api/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            assert websocket.receive_json()["code"] == "run_stopped"


def test_websocket_stale_run_sends_typed_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        run_id = client.post(
            "/api/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        harness.pty.close_master(harness.manager.get(run_id).terminal)
        with client.websocket_connect(
            f"/api/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            assert websocket.receive_json()["code"] == "run_stale"


def test_websocket_binary_input_reaches_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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


@pytest.mark.parametrize("cli_name", [CLAUDE_CLIENT_NAME, "codex"])
def test_spawn_request_uses_settings_default_passthrough(cli_name: str, tmp_path: Path) -> None:
    settings = Settings(
        cwd=tmp_path,
        default_client_passthrough=("--dangerously-skip-permissions", "--model", "sonnet"),
    )

    request = run_routes._spawn_request(run_routes.CreateRunRequest(cli=cli_name), settings)

    assert request.cli == cli_name
    assert request.passthrough == settings.default_client_passthrough
    assert request.cwd == tmp_path


def test_spawn_request_is_nested_capture_only(tmp_path: Path) -> None:
    # A captured run never allocates a nested web port: it is capture-only, the CLI's
    # web co-process stays external. The default lives in SpawnRun; assert it survives
    # the POST request builder so a managed run can never leak a bound web port.
    settings = Settings(cwd=tmp_path)

    request = run_routes._spawn_request(
        run_routes.CreateRunRequest(cli=CLAUDE_CLIENT_NAME, cwd=str(tmp_path)), settings
    )

    assert request.web_port is None
    assert request.web_runtime == "external"


def test_post_after_manager_close_returns_machine_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)
    asyncio.run(harness.manager.close())

    with client:
        response = client.post(
            "/api/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "run_manager_closed"


def test_run_manager_http_mapping_covers_declared_codes() -> None:
    assert set(run_routes._RUN_MANAGER_HTTP_STATUS) == set(get_args(RunManagerErrorCode))


def test_post_launch_failure_returns_machine_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = RunManager(
        dependencies=_fake_dependencies(), prepare_run=cast("Any", _raise_prepare_error)
    )
    monkeypatch.setattr(run_routes, "create_run_manager", lambda: manager)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/api/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "launch_failed"
    assert manager.list() == []


@dataclass
class FakeLease:
    manifest_path: Path
    sessions: list[TerminalPty]
    closed: bool = False
    lock_released: bool = False
    child_poll_at_close: int | None = None

    def close(self) -> None:
        self.child_poll_at_close = self.sessions[0].process.poll() if self.sessions else None
        self.closed = True
        self.lock_released = True
        self.manifest_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class FakeManagedClient:
    name: str
    display_name: str
    argv: list[str]
    env: Mapping[str, str]
    cwd: Path


@dataclass(frozen=True)
class FakeManagedSession:
    native_session_id: str
    source_descriptor: str


def install_real_pty_manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    argv: list[str],
    lease: FakeLease | None = None,
) -> tuple[RunManager, FakeLease]:
    """Install a RunManager that spawns a real PTY child, with prepare/lease faked.

    Shared by the managed-run terminal tests that need real PTY I/O (binary input,
    job control) without launching a true managed CLI. Patches run_routes so the
    app under test uses this manager.
    """
    sessions: list[TerminalPty] = []
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}")
    fake_lease = lease or FakeLease(manifest_path=manifest_path, sessions=sessions)

    def fake_prepare(
        request: CapturedRunRequest,
        **_kwargs: object,
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        working_dir = cast("Path", request.directory)
        spawn_spec = CapturedRunSpawnSpec(
            run_id="run-test",
            working_dir=working_dir,
            storage_dir=tmp_path / "storage",
            proxy_port=9900,
            web_port=None,
            mitmdump_log=tmp_path / "storage" / "mitmdump.log",
            client=cast(
                "Any",
                FakeManagedClient(
                    name=CLAUDE_CLIENT_NAME,
                    display_name="Claude",
                    argv=argv,
                    env={**os.environ, "PYTHONUNBUFFERED": "1", "TERM": "xterm-256color"},
                    cwd=working_dir,
                ),
            ),
            launch_env={},
            managed_session=cast(
                "Any",
                FakeManagedSession(
                    native_session_id="native-test",
                    source_descriptor='{"kind":"claude"}',
                ),
            ),
            client_name=request.client_name,
        )
        return spawn_spec, cast("CapturedRunLease", fake_lease)

    def tracking_spawn(
        *,
        argv: Sequence[str],
        env: Mapping[str, str],
        cwd: Path,
        cols: int,
        rows: int,
    ) -> TerminalPty:
        session = spawn_pty_process(argv=argv, env=env, cwd=cwd, cols=cols, rows=rows)
        sessions.append(session)
        return session

    manager = RunManager(
        dependencies=_fake_dependencies(),
        prepare_run=fake_prepare,
        spawn_pty=tracking_spawn,
    )
    monkeypatch.setattr(run_routes, "create_run_manager", lambda: manager)
    return manager, fake_lease


def _fake_dependencies() -> CapturedRunDependencies:
    return CapturedRunDependencies(
        require_addon=lambda: Path("addon.py"),
        resolve_mitmdump=lambda: "mitmdump",
        which=lambda *_args, **_kwargs: "fake",
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (8787, 8788),
        inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
        user_supplied_system_prompt=lambda _args: False,
        check_session_store=lambda: None,
    )


def _raise_prepare_error(_request: CapturedRunRequest, **_kwargs: object) -> Any:
    raise RuntimeError("prepare failed")


def _python_client_argv(script: str) -> list[str]:
    return [sys.executable, "-u", "-c", script]
