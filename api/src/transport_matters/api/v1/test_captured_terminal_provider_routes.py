"""Provider route regressions for captured terminal panes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from transport_matters.api.v1 import captured_terminal
from transport_matters.captured_run import (
    CODEX_CLIENT_NAME,
    WEB_RUNTIME_EXTERNAL,
    CapturedRunDependencies,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.config import Settings, get_settings
from transport_matters.main import create_app

if TYPE_CHECKING:
    from pathlib import Path


BACKEND_ORIGIN = "http://localhost:8788"


def test_claude_route_contract_is_unchanged_and_specific_first() -> None:
    routes = [getattr(route, "path", "") for route in captured_terminal.router.routes]

    assert captured_terminal.CAPTURED_CLAUDE_TERMINAL_ROUTE == ("/captured-runs/claude/terminal")
    assert routes.index(captured_terminal.CAPTURED_CLAUDE_TERMINAL_ROUTE) < routes.index(
        captured_terminal.CAPTURED_TERMINAL_ROUTE
    )


def test_unknown_captured_cli_is_rejected_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepare_called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal prepare_called
        prepare_called = True
        raise AssertionError("unknown cli must not reach captured run preparation")

    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(captured_terminal, "_prepare_captured_agent_run", fail_if_called)
    client = TestClient(create_app())

    with (
        client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/api/captured-runs/not-a-cli/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ),
    ):
        pass

    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
    assert prepare_called is False


def test_prepare_captured_codex_run_requests_nested_capture_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        cwd=tmp_path,
        agent_home_dir=tmp_path / "agent-home",
        debug=True,
    )
    dependencies = CapturedRunDependencies(
        require_addon=lambda: tmp_path / "addon.py",
        resolve_mitmdump=lambda: "/usr/bin/mitmdump",
        which=lambda *_args, **_kwargs: "/usr/bin/codex",
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (39223, 49223),
        inject_system_prompt=lambda *_args, **_kwargs: [],
        user_supplied_system_prompt=lambda _args: False,
        check_session_store=lambda: None,
    )
    captured: dict[str, Any] = {}

    def fake_prepare(
        request: CapturedRunRequest, **kwargs: object
    ) -> tuple[CapturedRunSpawnSpec, object]:
        captured["request"] = request
        captured["kwargs"] = kwargs
        return (
            CapturedRunSpawnSpec(
                run_id="run-codex",
                working_dir=tmp_path,
                storage_dir=tmp_path / "storage",
                proxy_port=39223,
                web_port=None,
                mitmdump_log=tmp_path / "storage" / "logs" / "mitmdump.log",
                client=None,
                launch_env={},
                managed_session=None,
                client_name=CODEX_CLIENT_NAME,
            ),
            object(),
        )

    monkeypatch.setattr(captured_terminal, "default_claude_run_dependencies", lambda: dependencies)
    monkeypatch.setattr(captured_terminal, "prepare_captured_run", fake_prepare)

    captured_terminal._prepare_captured_agent_run(
        cli=captured_terminal._validate_captured_run_cli(CODEX_CLIENT_NAME),
        cwd=None,
        settings=settings,
    )

    request = captured["request"]
    assert request.client_name == CODEX_CLIENT_NAME
    assert request.web_port is None
    assert request.web_runtime == WEB_RUNTIME_EXTERNAL
    assert request.upstream == ""
    assert request.directory == tmp_path.resolve()
    assert request.home_dir == settings.agent_home_dir
    assert captured["kwargs"]["port_in_use"] is dependencies.port_in_use


def _websocket_headers(origin: str, *, host: str = "localhost:8788") -> dict[str, str]:
    return {"Origin": origin, "Host": host}
