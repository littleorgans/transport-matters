from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, get_args
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from transport_matters import config, env_keys
from transport_matters.api.v1 import run_routes
from transport_matters.api.v1.session_store import (
    optional_session_pool as _ORIGINAL_OPTIONAL_SESSION_POOL,
)
from transport_matters.api.v1.test_terminal import _wait_until
from transport_matters.captured_run import (
    CLAUDE_HARNESS_NAME,
    CapturedRunLease,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.config import Settings
from transport_matters.main import create_app
from transport_matters.run_manager import RunManagerError, RunManagerErrorCode, RunState
from transport_matters.session.async_dao import AsyncSessionDao
from transport_matters.session.pool import create_async_pool
from transport_matters.session.test_foundation import event, root_session
from transport_matters.space.models import ResolvedWorktree, SpaceId, WorktreeId
from transport_matters.test_run_manager import (
    PreparedRunHarness,
    PtyHarness,
    make_manager,
    patch_pty_teardown,
    resolved_worktree,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import Request

    from transport_matters.session.testing import TestDb

BACKEND_ORIGIN = "http://localhost:8788"


class _FakePoolConnection:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakePool:
    def connection(self) -> _FakePoolConnection:
        return _FakePoolConnection()


def _install_space_store(
    monkeypatch: pytest.MonkeyPatch,
    resolved: ResolvedWorktree,
) -> ResolvedWorktree:
    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def resolve_worktree(
            self, requested: WorktreeId, *, owner: str = "local"
        ) -> ResolvedWorktree | None:
            assert owner == "local"
            if requested != resolved.worktree_id:
                return None
            return resolved

    def optional_session_pool(request: Request) -> object:
        return _ORIGINAL_OPTIONAL_SESSION_POOL(request) or _FakePool()

    monkeypatch.setattr(run_routes, "SpaceStore", Store, raising=False)
    monkeypatch.setattr(run_routes, "optional_session_pool", optional_session_pool)
    return resolved


class ManagedRunHarness:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.pty = PtyHarness()
        patch_pty_teardown(monkeypatch, self.pty)
        self.prepared = PreparedRunHarness(tmp_path)
        self.resolved = _install_space_store(monkeypatch, resolved_worktree(tmp_path))
        self.space_id = self.resolved.space_id
        self.worktree_id = self.resolved.worktree_id

        async def prepare_shared(
            request: CapturedRunRequest,
            **_: object,
        ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
            return self.prepared.prepare(request)

        monkeypatch.setattr(
            "transport_matters.run_manager.prepare_shared_captured_run",
            prepare_shared,
        )
        self.manager = make_manager(
            tmp_path,
            self.pty,
            self.prepared,
            shared_proxy_manager=object(),
        )
        monkeypatch.setattr(run_routes, "create_run_manager", lambda **_: self.manager)

    def body(self, harness: str = "claude", **extra: object) -> dict[str, object]:
        return {"harness": harness, "worktreeId": str(self.worktree_id), **extra}


def test_post_get_attach_detach_and_terminate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        create_response = client.post(
            "/v1/runs",
            json=harness.body(),
            headers=_http_headers(BACKEND_ORIGIN),
        )
        assert create_response.status_code == 201
        run = create_response.json()["run"]
        assert set(run) == {
            "runId",
            "spaceId",
            "worktreeId",
            "sessionId",
            "harness",
            "state",
            "createdAt",
        }
        assert run["spaceId"] == str(harness.space_id)
        assert run["worktreeId"] == str(harness.worktree_id)
        assert run["state"] == "RUNNING"
        run_id = run["runId"]

        listed = client.get("/v1/runs", headers=_http_headers(BACKEND_ORIGIN)).json()
        assert [item["runId"] for item in listed["items"]] == [run_id]
        assert listed["nextCursor"] is None

        managed = harness.manager.get(run_id)
        assert managed.terminal is None

        with client.websocket_connect(
            f"/v1/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "run.terminal.ready"
            assert set(ready["run"]) == {
                "runId",
                "spaceId",
                "worktreeId",
                "sessionId",
                "harness",
                "state",
                "createdAt",
            }
            assert ready["scrollback"]["replayedBytes"] == 0
            assert websocket.receive_json() == {"type": "run.terminal.scrollback-end"}
            terminal = managed.terminal
            assert terminal is not None
            harness.pty.write(terminal, b"live")
            assert websocket.receive_bytes() == b"live"

        _wait_until(lambda: harness.manager.get(run_id).view().viewer_count == 0)
        with client.websocket_connect(
            f"/v1/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "run.terminal.ready"
            assert ready["scrollback"]["replayedBytes"] == len(b"live")
            assert websocket.receive_bytes() == b"live"
            assert websocket.receive_json() == {"type": "run.terminal.scrollback-end"}

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
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        create_response = client.post(
            "/v1/runs",
            json=harness.body(),
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
    assert set(single_run) == {
        "runId",
        "spaceId",
        "worktreeId",
        "sessionId",
        "harness",
        "state",
        "createdAt",
    }
    assert single_run["spaceId"] == str(harness.space_id)
    assert single_run["worktreeId"] == str(harness.worktree_id)
    assert "workspaceId" not in single_run
    assert "nativeSessionId" not in single_run
    assert "proxyPort" not in single_run
    assert "webPort" not in single_run
    assert "storageDir" not in single_run
    assert "scrollbackBytes" not in single_run
    assert "viewerlessSince" not in single_run


def test_post_run_resolves_worktree_id_and_serializes_space_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    space_id = SpaceId.from_uuid(UUID("11111111-1111-4111-8111-111111111111"))
    worktree_id = WorktreeId.from_uuid(UUID("22222222-2222-4222-8222-222222222222"))
    resolved = ResolvedWorktree(
        space_id=space_id,
        worktree_id=worktree_id,
        cwd=str(tmp_path),
        workspace_slug="workspace",
        workspace_hash="hash1",
        missing=False,
        archived=False,
    )
    _install_space_store(monkeypatch, resolved)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json={"harness": "claude", "worktreeId": str(worktree_id)},
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 201
    run = response.json()["run"]
    assert set(run) == {
        "runId",
        "spaceId",
        "worktreeId",
        "sessionId",
        "harness",
        "state",
        "createdAt",
    }
    assert run["spaceId"] == str(space_id)
    assert run["worktreeId"] == str(worktree_id)
    assert "workspaceId" not in run
    spawned = harness.manager.get(run["runId"])
    assert spawned.space_id == space_id
    assert spawned.worktree_id == worktree_id


def test_legacy_api_runs_path_is_removed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.get("/api/runs", headers=_http_headers(BACKEND_ORIGIN))

    assert response.status_code == 404


def test_list_runs_uses_items_envelope_and_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        first_id = client.post(
            "/v1/runs",
            json=harness.body(),
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        second_id = client.post(
            "/v1/runs",
            json=harness.body(),
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
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        for _ in range(2):
            client.post(
                "/v1/runs",
                json=harness.body(),
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
            json=harness.body(),
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
            json=harness.body(),
            headers=_http_headers("http://evil.test"),
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "origin_not_allowed"
    assert harness.manager.list() == []


def test_post_rejects_missing_worktree_id_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json={"harness": "claude"},
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "worktree_required"
    assert harness.manager.list() == []


def test_post_rejects_unsupported_harness_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json=harness.body("unknown"),
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_harness"
    assert harness.manager.list() == []


def test_post_continuation_threads_lineage_context_and_idempotency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_db: TestDb
) -> None:
    asyncio.run(_seed_continuation_parent(test_db.database_url))
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    monkeypatch.setenv(env_keys.DATABASE_URL, test_db.database_url)
    monkeypatch.setattr(
        "transport_matters.main.resolve_database_url",
        lambda _settings: test_db.database_url,
    )
    client = _client(monkeypatch, tmp_path)
    body = {
        "harness": "claude",
        "worktreeId": str(harness.worktree_id),
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
                "harness": "claude",
                "worktreeId": str(harness.worktree_id),
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
                "harness": "claude",
                "worktreeId": str(harness.worktree_id),
                "continueFromSessionId": "parent-session",
            },
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_request"
    assert harness.manager.list() == []
    assert harness.prepared.requests == []


def test_post_runtime_template_resolves_and_sets_spawn_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template = tmp_path / ".agent-runtimes" / "runtimes" / "codex-base"
    template.mkdir(parents=True)
    (template / "runtime.toml").write_text("[runtime]\n", encoding="utf-8")
    (template / ".git").mkdir()
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json={
                "harness": "codex",
                "worktreeId": str(harness.worktree_id),
                "runtimeTemplate": "codex-base",
            },
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 201
    assert len(harness.prepared.requests) == 1
    captured = harness.prepared.requests[0]
    assert captured.runtime_template is not None
    assert captured.runtime_template.template_id == "codex-base"
    assert captured.runtime_template.harness == "codex"
    assert captured.runtime_template.template_home == template.resolve()
    assert captured.runtime_template.provenance == {
        "registry_source": "agent-runtimes",
        "registry_root": str((tmp_path / ".agent-runtimes" / "runtimes").resolve()),
    }
    assert captured.launch_fields == {}


def test_post_bypass_permissions_sets_spawn_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json={
                "harness": "claude",
                "worktreeId": str(harness.worktree_id),
                "bypassPermissions": True,
            },
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 201
    assert len(harness.prepared.requests) == 1
    captured = harness.prepared.requests[0]
    assert captured.bypass_permissions is True


def test_post_empty_runtime_template_preserves_native_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json=harness.body(runtimeTemplate="  "),
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 201
    assert len(harness.prepared.requests) == 1
    assert harness.prepared.requests[0].runtime_template is None


def test_post_missing_runtime_template_returns_machine_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json=harness.body("codex", runtimeTemplate="missing"),
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_runtime_template"
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


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    config.get_settings.cache_clear()
    return TestClient(create_app())


def _http_headers(origin: str, *, host: str = "localhost:8788") -> dict[str, str]:
    return {"origin": origin, "host": host}


def _websocket_headers(origin: str, *, host: str = "localhost:8788") -> dict[str, str]:
    return {"origin": origin, "host": host}


@pytest.mark.parametrize("harness_name", [CLAUDE_HARNESS_NAME, "codex"])
def test_spawn_request_ignores_settings_default_passthrough(
    harness_name: str, tmp_path: Path
) -> None:
    resolved = resolved_worktree(tmp_path)
    settings = Settings(
        cwd=tmp_path,
        default_client_passthrough=("--dangerously-skip-permissions", "--model", "sonnet"),
    )

    request = run_routes._spawn_request(
        run_routes.CreateRunRequest(harness=harness_name, worktreeId=str(resolved.worktree_id)),
        settings,
        resolved_worktree=resolved,
    )

    assert request.harness == harness_name
    assert request.passthrough == ()
    assert request.resolved_worktree == resolved


def test_spawn_request_is_nested_capture_only(tmp_path: Path) -> None:
    # A captured run never allocates a nested web port: it is capture-only, the harness
    # web co-process stays external. Pane launch passthrough stays explicit and empty,
    # so a managed run can never leak stale desktop passthrough or a bound web port.
    resolved = resolved_worktree(tmp_path)
    settings = Settings(cwd=tmp_path)

    request = run_routes._spawn_request(
        run_routes.CreateRunRequest(
            harness=CLAUDE_HARNESS_NAME, worktreeId=str(resolved.worktree_id)
        ),
        settings,
        resolved_worktree=resolved,
    )

    assert request.web_port is None
    assert request.web_runtime == "external"
    assert request.bypass_permissions is False


def test_post_after_manager_close_returns_machine_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    client = _client(monkeypatch, tmp_path)
    asyncio.run(harness.manager.close())

    with client:
        response = client.post(
            "/v1/runs",
            json=harness.body(),
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "run_manager_closed"


def test_post_proxy_unavailable_returns_machine_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _install_space_store(monkeypatch, resolved_worktree(tmp_path))

    class UnavailableManager:
        async def spawn(self, _request: object) -> object:
            raise RunManagerError(
                "proxy_start_timeout",
                "shared proxy unavailable: mitmdump missing",
            )

    monkeypatch.setattr(run_routes, "create_run_manager", lambda **_: UnavailableManager())
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json={"harness": "claude", "worktreeId": str(resolved.worktree_id)},
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "proxy_start_timeout",
        "message": "shared proxy unavailable: mitmdump missing",
    }


def test_run_manager_http_mapping_covers_declared_codes() -> None:
    assert set(run_routes._RUN_MANAGER_HTTP_STATUS) == set(get_args(RunManagerErrorCode))


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
