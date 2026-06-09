"""Captured terminal web separation regressions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from transport_matters.api.v1 import captured_terminal
from transport_matters.captured_run import (
    CapturedRunDependencies,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.config import Settings

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _spawn_spec(tmp_path: Path) -> CapturedRunSpawnSpec:
    return CapturedRunSpawnSpec(
        run_id="run-nested",
        working_dir=tmp_path,
        storage_dir=tmp_path / "storage",
        proxy_port=39123,
        web_port=None,
        mitmdump_log=tmp_path / "storage" / "logs" / "mitmdump.log",
        client=None,
        launch_env={},
        managed_session=None,
    )


def test_prepare_captured_claude_run_requests_nested_capture_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        cwd=tmp_path,
        web_port=8788,
        agent_home_dir=tmp_path / "agent-home",
        debug=True,
    )

    def port_in_use(port: int) -> bool:
        return port == settings.web_port

    dependencies = CapturedRunDependencies(
        require_addon=lambda: tmp_path / "addon.py",
        resolve_mitmdump=lambda: "/usr/bin/mitmdump",
        which=lambda *_args, **_kwargs: "/usr/bin/claude",
        port_in_use=port_in_use,
        allocate_port_pair=lambda: (39123, 49123),
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
        return _spawn_spec(tmp_path), object()

    monkeypatch.setattr(captured_terminal, "default_claude_run_dependencies", lambda: dependencies)
    monkeypatch.setattr(captured_terminal, "prepare_captured_run", fake_prepare)

    _spawn_spec_result, _lease = captured_terminal._prepare_captured_claude_run(
        cwd=None,
        settings=settings,
    )

    request = captured["request"]
    assert request.web_port is None
    assert request.web_runtime == "external"
    assert request.directory == tmp_path.resolve()
    assert request.home_dir == settings.agent_home_dir
    assert captured["kwargs"]["port_in_use"] is dependencies.port_in_use
    assert captured["kwargs"]["port_in_use"](settings.web_port) is True


def test_ready_frame_omits_nested_web_port(tmp_path: Path) -> None:
    frame = captured_terminal._ready_frame(_spawn_spec(tmp_path))

    assert frame["type"] == "captured-run.ready"
    assert frame["proxyPort"] == 39123
    assert "webPort" not in frame
