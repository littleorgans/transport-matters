"""Captured-run launch separation regressions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from transport_matters import env_keys
from transport_matters.captured_run import (
    CLAUDE_CLIENT_NAME,
    CLAUDE_UPSTREAM_DEFAULT,
    WEB_RUNTIME_EXTERNAL,
    CapturedRunRequest,
    prepare_captured_run,
)
from transport_matters.cli.net import loopback_http_url

if TYPE_CHECKING:
    from pathlib import Path


class FakeSupervisor:
    def __init__(self) -> None:
        self.signal_handlers_installed = False
        self.terminated = False
        self.restored = False

    def install_signal_handlers(self) -> None:
        self.signal_handlers_installed = True

    def terminate_all(self) -> None:
        self.terminated = True

    def restore_signal_handlers(self) -> None:
        self.restored = True


def test_prepare_captured_run_external_web_starts_capture_only_proxy(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    addon_path = tmp_path / "addon.py"
    addon_path.write_text("# addon\n")
    started: list[dict[str, Any]] = []
    supervisors: list[FakeSupervisor] = []

    def supervisor_factory() -> FakeSupervisor:
        supervisor = FakeSupervisor()
        supervisors.append(supervisor)
        return supervisor

    def proxy_starter(**kwargs: Any) -> None:
        started.append(kwargs)
        assert kwargs["web_port"] is None
        assert env_keys.WEB_PORT not in kwargs["mitmdump_env"]
        assert kwargs["mitmdump_env"][env_keys.WEB_RUNTIME] == WEB_RUNTIME_EXTERNAL
        return

    def inject_system_prompt(*_args: object, **_kwargs: object) -> list[str]:
        raise AssertionError("capture-only nested runs must not inject an inspector prompt")

    spawn_spec, lease = prepare_captured_run(
        CapturedRunRequest(
            client_name=CLAUDE_CLIENT_NAME,
            passthrough=(),
            directory=workspace,
            proxy_port=None,
            web_port=None,
            upstream=CLAUDE_UPSTREAM_DEFAULT,
            storage_dir=tmp_path / "storage",
            home_dir=tmp_path / "agent-home",
            client_bin=None,
            client_disabled=False,
            no_system_prompt=False,
            debug=False,
            web_runtime=WEB_RUNTIME_EXTERNAL,
        ),
        require_addon=lambda: addon_path,
        resolve_mitmdump=lambda: "/usr/bin/mitmdump",
        which=lambda *_args, **_kwargs: "/usr/bin/claude",
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (39123, 49123),
        inject_system_prompt=inject_system_prompt,
        user_supplied_system_prompt=lambda _args: False,
        supervisor_factory=supervisor_factory,
        proxy_starter=proxy_starter,
        env={},
    )

    try:
        assert spawn_spec.web_port is None
        assert spawn_spec.launch_env[env_keys.PROXY_PORT] == "39123"
        assert env_keys.WEB_PORT not in spawn_spec.launch_env
        assert spawn_spec.launch_env[env_keys.WEB_RUNTIME] == WEB_RUNTIME_EXTERNAL
        assert spawn_spec.client is not None
        assert spawn_spec.client.env["ANTHROPIC_BASE_URL"] == loopback_http_url(
            spawn_spec.proxy_port
        )
        assert started and started[0]["proxy_port"] == spawn_spec.proxy_port
    finally:
        lease.close()

    assert supervisors[0].terminated is True
    assert supervisors[0].restored is True
