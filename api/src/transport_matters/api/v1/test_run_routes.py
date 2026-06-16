from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, get_args

import pytest
from fastapi.testclient import TestClient

from transport_matters import config, env_keys
from transport_matters.api.v1 import run_routes, terminal_bridge
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
from transport_matters.session.async_dao import AsyncSessionDao
from transport_matters.session.pool import create_async_pool
from transport_matters.session.test_foundation import event, root_session
from transport_matters.test_run_manager import (
    PreparedRunHarness,
    PtyHarness,
    make_manager,
    patch_pty_teardown,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from transport_matters.session.testing import TestDb

BACKEND_ORIGIN = "http://localhost:8788"


class ManagedRunHarness:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.pty = PtyHarness()
        patch_pty_teardown(monkeypatch, self.pty)
        self.prepared = PreparedRunHarness(tmp_path)
        self.manager = make_manager(tmp_path, self.pty, self.prepared)
        monkeypatch.setattr(run_routes, "create_run_manager", lambda: self.manager)


def test_post_get_attach_detach_and_terminate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        create_response = client.post(
            "/v1/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        )
        assert create_response.status_code == 201
        run = create_response.json()["run"]
        assert set(run) == {"runId", "workspaceId", "sessionId", "cli", "state", "createdAt"}
        assert run["state"] == "RUNNING"
        run_id = run["runId"]

        listed = client.get("/v1/runs", headers=_http_headers(BACKEND_ORIGIN)).json()
        assert [item["runId"] for item in listed["items"]] == [run_id]
        assert listed["nextCursor"] is None

        managed = harness.manager.get(run_id)
        harness.pty.write(managed.terminal, b"past")
        _wait_until(lambda: managed.scrollback.total_bytes >= len(b"past"))

        with client.websocket_connect(
            f"/v1/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "run.terminal.ready"
            assert set(ready["run"]) == {
                "runId",
                "workspaceId",
                "sessionId",
                "cli",
                "state",
                "createdAt",
            }
            assert ready["scrollback"]["replayedBytes"] == len(b"past")
            assert websocket.receive_bytes() == b"past"
            assert websocket.receive_json() == {"type": "run.terminal.scrollback-end"}
            harness.pty.write(managed.terminal, b"live")
            assert websocket.receive_bytes() == b"live"

        _wait_until(lambda: harness.manager.get(run_id).view().viewer_count == 0)
        still_running = client.get(
            f"/v1/runs?state={RunState.RUNNING}",
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()
        assert [item["runId"] for item in still_running["items"]] == [run_id]

        terminate_response = client.post(
            f"/v1/runs/{run_id}/terminate",
            headers=_http_headers(BACKEND_ORIGIN),
        )
        assert terminate_response.status_code == 200
        terminated = terminate_response.json()["run"]
        assert terminated["runId"] == run_id
        assert terminated["state"] == "TERMINATED"
        assert terminated["endReason"] == "explicit"


def test_run_views_hide_internal_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        create_response = client.post(
            "/v1/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run"]["runId"]

        listed = client.get("/v1/runs", headers=_http_headers(BACKEND_ORIGIN))
        assert listed.status_code == 200
        listed_run = listed.json()["items"][0]

        single = client.get(f"/v1/runs/{run_id}", headers=_http_headers(BACKEND_ORIGIN))
        assert single.status_code == 200
        single_run = single.json()["run"]

    assert listed_run == single_run
    assert set(single_run) == {"runId", "workspaceId", "sessionId", "cli", "state", "createdAt"}
    assert "nativeSessionId" not in single_run
    assert "proxyPort" not in single_run
    assert "webPort" not in single_run
    assert "storageDir" not in single_run
    assert "scrollbackBytes" not in single_run
    assert "viewerlessSince" not in single_run


def test_legacy_api_runs_path_is_removed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.get("/api/runs", headers=_http_headers(BACKEND_ORIGIN))

    assert response.status_code == 404


def test_list_runs_uses_items_envelope_and_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        first_id = client.post(
            "/v1/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        second_id = client.post(
            "/v1/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]

        first_page = client.get("/v1/runs?limit=1", headers=_http_headers(BACKEND_ORIGIN))
        assert first_page.status_code == 200
        first_payload = first_page.json()
        assert [item["runId"] for item in first_payload["items"]] == [first_id]
        assert isinstance(first_payload["nextCursor"], str)

        second_page = client.get(
            f"/v1/runs?limit=1&cursor={first_payload['nextCursor']}",
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert [item["runId"] for item in second_payload["items"]] == [second_id]
    assert second_payload["nextCursor"] is None


def test_list_runs_rejects_cursor_for_different_filters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        for _ in range(2):
            client.post(
                "/v1/runs",
                json={"cli": "claude", "cwd": str(tmp_path)},
                headers=_http_headers(BACKEND_ORIGIN),
            )
        first_page = client.get("/v1/runs?limit=1", headers=_http_headers(BACKEND_ORIGIN))
        response = client.get(
            f"/v1/runs?state=RUNNING&cursor={first_page.json()['nextCursor']}",
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_cursor"


def test_terminate_run_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        run_id = client.post(
            "/v1/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]

        first = client.post(
            f"/v1/runs/{run_id}/terminate",
            headers=_http_headers(BACKEND_ORIGIN),
        )
        second = client.post(
            f"/v1/runs/{run_id}/terminate",
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
            "/v1/runs",
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
            "/v1/runs",
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
            "/v1/runs",
            json={"cli": "unknown", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_cli"
    assert harness.manager.list() == []


def test_post_continuation_threads_lineage_context_and_idempotency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_db: TestDb
) -> None:
    asyncio.run(_seed_continuation_parent(test_db.database_url))
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    monkeypatch.setenv(env_keys.DATABASE_URL, test_db.database_url)
    client = _client(monkeypatch, tmp_path)
    body = {
        "cli": "claude",
        "cwd": str(tmp_path),
        "continueFromSessionId": "parent-session",
        "idempotencyKey": "resume-click-1",
    }

    with client:
        first = client.post("/v1/runs", json=body, headers=_http_headers(BACKEND_ORIGIN))
        second = client.post("/v1/runs", json=body, headers=_http_headers(BACKEND_ORIGIN))

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["run"]["runId"] == first.json()["run"]["runId"]
    assert len(harness.prepared.requests) == 1
    captured = harness.prepared.requests[0]
    assert captured.launch_fields == {
        "continue_from_session_id": "parent-session",
        "parent_session_id": "parent-session",
        "forked_at_seq": 1,
        "session_purpose": "continuation",
        "resume_context": {
            "firstUserPrompt": "first prompt",
            "lastAgentMessage": "last answer",
            "transcriptRef": "parent-session",
        },
    }


def test_post_continuation_returns_not_found_for_foreign_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_db: TestDb
) -> None:
    asyncio.run(_seed_continuation_parent(test_db.database_url, owner="other"))
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    monkeypatch.setenv(env_keys.DATABASE_URL, test_db.database_url)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json={
                "cli": "claude",
                "cwd": str(tmp_path),
                "continueFromSessionId": "parent-session",
                "idempotencyKey": "resume-click-1",
            },
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "session_not_found"
    assert harness.manager.list() == []
    assert harness.prepared.requests == []


def test_post_continuation_requires_idempotency_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json={
                "cli": "claude",
                "cwd": str(tmp_path),
                "continueFromSessionId": "parent-session",
            },
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_request"
    assert harness.manager.list() == []
    assert harness.prepared.requests == []


def test_terminate_unknown_run_returns_machine_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs/missing/terminate",
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
            json={"cli": "claude", "cwd": str(tmp_path)},
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
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        harness.pty.close_master(harness.manager.get(run_id).terminal)
        with client.websocket_connect(
            f"/v1/runs/{run_id}/terminal",
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
            "/v1/runs",
            json={"cli": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        with client.websocket_connect(
            f"/v1/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            assert websocket.receive_json()["type"] == "run.terminal.ready"
            assert websocket.receive_json() == {"type": "run.terminal.scrollback-end"}
            websocket.send_bytes(b"ping\n")
            output = _receive_until_disconnect(websocket, needle=b"ECHO:ping")
            assert b"ECHO:ping" in output
        _wait_until(lambda: manager.get(run_id).state is RunState.EXITED)


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
            json={"cli": "claude", "cwd": str(tmp_path)},
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
            "/v1/runs",
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
            "/v1/runs",
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


async def _seed_continuation_parent(database_url: str, *, owner: str = "local") -> None:
    async with (
        create_async_pool(database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        dao = AsyncSessionDao(conn)
        await dao.upsert_session(
            root_session("parent-session", native_session_id="native-parent").model_copy(
                update={"owner": owner}
            )
        )
        await dao.insert_event(
            event(0, session_id="parent-session", search_text="first prompt").model_copy(
                update={
                    "role": "user",
                    "ir": {"parts": [{"type": "text", "text": "first prompt"}]},
                }
            )
        )
        await dao.insert_event(
            event(1, session_id="parent-session", search_text="last answer").model_copy(
                update={"role": "assistant"}
            )
        )
        await dao.insert_event(
            event(2, session_id="parent-session", search_text="sidechain").model_copy(
                update={"role": "assistant", "is_sidechain": True}
            )
        )


def _raise_prepare_error(_request: CapturedRunRequest, **_kwargs: object) -> Any:
    raise RuntimeError("prepare failed")


def _python_client_argv(script: str) -> list[str]:
    return [sys.executable, "-u", "-c", script]
