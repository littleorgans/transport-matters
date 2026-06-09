from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from transport_matters import config
from transport_matters.api.v1 import captured_terminal, run_routes
from transport_matters.captured_run import CLAUDE_CLIENT_NAME, CODEX_CLIENT_NAME
from transport_matters.config import Settings
from transport_matters.main import create_app

if TYPE_CHECKING:
    from pathlib import Path

    from transport_matters.run_manager import CapturedRunCli

BACKEND_ORIGIN = "http://localhost:8788"


def test_captured_terminal_routes_do_not_accept_ws_passthrough() -> None:
    for route in captured_terminal.router.routes:
        if getattr(route, "path", "") == captured_terminal.CAPTURED_TERMINAL_ROUTE:
            assert "passthrough" not in getattr(route, "param_convertors", {})


@pytest.mark.parametrize("cli_name", [CLAUDE_CLIENT_NAME, CODEX_CLIENT_NAME])
def test_captured_spawn_request_uses_settings_default_passthrough(
    cli_name: str, tmp_path: Path
) -> None:
    settings = Settings(
        cwd=tmp_path,
        default_client_passthrough=("--dangerously-skip-permissions", "--model", "sonnet"),
    )

    request = run_routes.captured_spawn_request(
        cli=cast("CapturedRunCli", cli_name),
        cwd=None,
        cols=80,
        rows=24,
        settings=settings,
    )

    assert request.cli == cli_name
    assert request.passthrough == settings.default_client_passthrough
    assert request.web_runtime == "external"
    assert request.cwd == tmp_path


def test_captured_spawn_request_requests_nested_capture_only(tmp_path: Path) -> None:
    settings = Settings(cwd=tmp_path)

    request = run_routes.captured_spawn_request(
        cli=cast("CapturedRunCli", CLAUDE_CLIENT_NAME),
        cwd=None,
        cols=80,
        rows=24,
        settings=settings,
    )

    assert request.web_port is None
    assert request.web_runtime == "external"


def test_unknown_captured_cli_is_rejected_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from transport_matters.api.v1.test_captured_terminal import (
        _python_client_argv,
        install_real_pty_manager,
    )

    manager, _lease = install_real_pty_manager(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv("print('never')\n"),
    )
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/api/captured-runs/nope/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ),
    ):
        pass

    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
    assert manager.list() == []


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    config.get_settings.cache_clear()
    return TestClient(create_app())


def _websocket_headers(origin: str, *, host: str = "localhost:8788") -> dict[str, str]:
    return {"origin": origin, "host": host}
