"""Captured-run launch separation regressions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from transport_matters import env_keys
from transport_matters.captured_run import (
    CLAUDE_CLIENT_NAME,
    CLAUDE_UPSTREAM_DEFAULT,
    CODEX_CLIENT_NAME,
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
            passthrough=("--dangerously-skip-permissions",),
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
            default_client_passthrough=("--dangerously-skip-permissions",),
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
        assert (
            spawn_spec.launch_env[env_keys.DEFAULT_CLIENT_PASSTHROUGH]
            == '["--dangerously-skip-permissions"]'
        )
        assert spawn_spec.client is not None
        assert "--dangerously-skip-permissions" in spawn_spec.client.argv
        assert spawn_spec.client.env["ANTHROPIC_BASE_URL"] == loopback_http_url(
            spawn_spec.proxy_port
        )
        assert started and started[0]["proxy_port"] == spawn_spec.proxy_port
    finally:
        lease.close()

    assert supervisors[0].terminated is True
    assert supervisors[0].restored is True


def test_prepare_captured_run_codex_external_web_uses_explicit_proxy_env(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    addon_path = tmp_path / "addon.py"
    addon_path.write_text("# addon\n")
    ca_path = tmp_path / "codex-ca.pem"
    ca_path.write_text("codex ca\n")
    started: list[dict[str, Any]] = []
    supervisors: list[FakeSupervisor] = []

    def supervisor_factory() -> FakeSupervisor:
        supervisor = FakeSupervisor()
        supervisors.append(supervisor)
        return supervisor

    def proxy_starter(**kwargs: Any) -> None:
        started.append(kwargs)
        assert kwargs["web_port"] is None
        assert "--mode" in kwargs["mitmdump_argv"]
        assert "regular" in kwargs["mitmdump_argv"]
        assert env_keys.WEB_PORT not in kwargs["mitmdump_env"]
        assert kwargs["mitmdump_env"][env_keys.CLI] == CODEX_CLIENT_NAME
        assert kwargs["mitmdump_env"][env_keys.WEB_RUNTIME] == WEB_RUNTIME_EXTERNAL
        return

    def inject_system_prompt(*_args: object, **_kwargs: object) -> list[str]:
        raise AssertionError("Codex captured panes must not use Anthropic prompt injection")

    spawn_spec, lease = prepare_captured_run(
        CapturedRunRequest(
            client_name=CODEX_CLIENT_NAME,
            passthrough=("--dangerously-skip-permissions",),
            directory=workspace,
            proxy_port=None,
            web_port=None,
            upstream="",
            storage_dir=tmp_path / "storage",
            home_dir=tmp_path / "agent-home",
            client_bin=None,
            client_disabled=False,
            no_system_prompt=False,
            debug=False,
            web_runtime=WEB_RUNTIME_EXTERNAL,
            default_client_passthrough=("--dangerously-skip-permissions",),
        ),
        require_addon=lambda: addon_path,
        resolve_mitmdump=lambda: "/usr/bin/mitmdump",
        which=lambda name, *_args, **_kwargs: f"/usr/bin/{name}",
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (39223, 49223),
        inject_system_prompt=inject_system_prompt,
        user_supplied_system_prompt=lambda _args: False,
        supervisor_factory=supervisor_factory,
        proxy_starter=proxy_starter,
        env={"CODEX_CA_CERTIFICATE": str(ca_path)},
    )

    try:
        assert spawn_spec.client_name == CODEX_CLIENT_NAME
        assert spawn_spec.web_port is None
        assert spawn_spec.launch_env[env_keys.PROXY_PORT] == "39223"
        assert env_keys.WEB_PORT not in spawn_spec.launch_env
        assert spawn_spec.launch_env[env_keys.WEB_RUNTIME] == WEB_RUNTIME_EXTERNAL
        assert (
            spawn_spec.launch_env[env_keys.DEFAULT_CLIENT_PASSTHROUGH]
            == '["--dangerously-skip-permissions"]'
        )
        assert spawn_spec.client is not None
        assert spawn_spec.client.name == CODEX_CLIENT_NAME
        assert "--dangerously-skip-permissions" in spawn_spec.client.argv
        assert spawn_spec.client.env["HTTPS_PROXY"] == loopback_http_url(spawn_spec.proxy_port)
        assert spawn_spec.client.env["HTTP_PROXY"] == loopback_http_url(spawn_spec.proxy_port)
        assert spawn_spec.client.env["CODEX_CA_CERTIFICATE"] == str(ca_path)
        assert spawn_spec.client.env["CODEX_NETWORK_PROXY_ACTIVE"] == "1"
        assert "ANTHROPIC_BASE_URL" not in spawn_spec.client.env
        assert started and started[0]["proxy_port"] == spawn_spec.proxy_port
    finally:
        lease.close()

    assert supervisors[0].terminated is True
    assert supervisors[0].restored is True
