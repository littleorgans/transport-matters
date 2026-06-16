"""Captured-run launch separation regressions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
from transport_matters.index.adapters.base import FileTailSource, decode_source_descriptor


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
        # An explicit --agent-home-dir is overlaid before launch. The addon
        # descriptor and child env must share the actual launched home.
        assert spawn_spec.launch_env[env_keys.AGENT_HOME_DIR] == str(
            tmp_path / "storage" / "runtime-home" / CLAUDE_CLIENT_NAME
        )
        assert started and started[0]["proxy_port"] == spawn_spec.proxy_port
    finally:
        lease.close()

    assert supervisors[0].terminated is True
    assert supervisors[0].restored is True


def test_prepare_captured_run_native_home_does_not_publish_agent_home_dir(
    tmp_path: Path,
) -> None:
    # A native launch (no --agent-home-dir) must keep AGENT_HOME_DIR unset: resolving the
    # overlay source to ~/.claude is an internal detail and must not be promoted onto the
    # launch env, or the desktop event publishes homeDir=~/.claude and the embedded backend
    # inherits it as agent_home_dir and stamps a Claude home onto Codex spawns (overlay
    # daemon assert -> 500). Regression for the #108 home_dir promotion.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "source-claude"
    source.mkdir()
    addon_path = tmp_path / "addon.py"
    addon_path.write_text("# addon\n")
    supervisors: list[FakeSupervisor] = []

    def supervisor_factory() -> FakeSupervisor:
        supervisor = FakeSupervisor()
        supervisors.append(supervisor)
        return supervisor

    def proxy_starter(**_kwargs: Any) -> None:
        return

    spawn_spec, lease = prepare_captured_run(
        CapturedRunRequest(
            client_name=CLAUDE_CLIENT_NAME,
            passthrough=("--dangerously-skip-permissions",),
            directory=workspace,
            proxy_port=None,
            web_port=None,
            upstream=CLAUDE_UPSTREAM_DEFAULT,
            storage_dir=tmp_path / "storage",
            home_dir=None,
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
        allocate_port_pair=lambda: (39323, 49323),
        inject_system_prompt=lambda *_a, **_k: ["--dangerously-skip-permissions"],
        user_supplied_system_prompt=lambda _args: False,
        supervisor_factory=supervisor_factory,
        proxy_starter=proxy_starter,
        env={"CLAUDE_CONFIG_DIR": str(source)},
    )

    try:
        # The native home is never published onto the launch env (the leak vector)...
        assert env_keys.AGENT_HOME_DIR not in spawn_spec.launch_env
        assert spawn_spec.client is not None
        assert env_keys.AGENT_HOME_DIR not in spawn_spec.client.env
        # ...yet the overlay is still built: the child's CLAUDE_CONFIG_DIR is the per-run
        # runtime overlay, not the source home.
        assert spawn_spec.client.env["CLAUDE_CONFIG_DIR"] == str(
            tmp_path / "storage" / "runtime-home" / CLAUDE_CLIENT_NAME
        )
    finally:
        lease.close()


def test_prepare_captured_run_claude_manual_home_descriptor_matches_launch_home(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source_home = tmp_path / "agent-home"
    source_home.mkdir()
    (source_home / ".claude.json").write_text("{}", encoding="utf-8")
    addon_path = tmp_path / "addon.py"
    addon_path.write_text("# addon\n")
    storage = tmp_path / "storage"
    supervisors: list[FakeSupervisor] = []

    def supervisor_factory() -> FakeSupervisor:
        supervisor = FakeSupervisor()
        supervisors.append(supervisor)
        return supervisor

    spawn_spec, lease = prepare_captured_run(
        CapturedRunRequest(
            client_name=CLAUDE_CLIENT_NAME,
            passthrough=("--dangerously-skip-permissions",),
            directory=workspace,
            proxy_port=None,
            web_port=None,
            upstream=CLAUDE_UPSTREAM_DEFAULT,
            storage_dir=storage,
            home_dir=source_home,
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
        allocate_port_pair=lambda: (39423, 49423),
        inject_system_prompt=lambda *_a, **_k: ["--dangerously-skip-permissions"],
        user_supplied_system_prompt=lambda _args: False,
        supervisor_factory=supervisor_factory,
        proxy_starter=lambda **_kwargs: None,
        env={"CLAUDE_CONFIG_DIR": str(source_home)},
    )

    try:
        assert spawn_spec.client is not None
        assert spawn_spec.managed_session is not None
        launch_home = Path(spawn_spec.client.env["CLAUDE_CONFIG_DIR"])
        assert launch_home == storage / "runtime-home" / CLAUDE_CLIENT_NAME
        assert launch_home != source_home
        assert spawn_spec.launch_env[env_keys.AGENT_HOME_DIR] == str(launch_home)
        assert (
            spawn_spec.launch_env[env_keys.OWNED_SOURCE_DESCRIPTOR]
            == spawn_spec.managed_session.source_descriptor
        )
        source = decode_source_descriptor(spawn_spec.managed_session.source_descriptor)
        assert isinstance(source, FileTailSource)
        assert source.home_dir == str(launch_home)
        assert Path(source.path).is_relative_to(launch_home / "projects")
    finally:
        lease.close()


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


def test_prepare_captured_run_codex_manual_home_seeds_runtime_home(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source_home = tmp_path / "agent-home"
    source_home.mkdir()
    addon_path = tmp_path / "addon.py"
    addon_path.write_text("# addon\n")
    ca_path = tmp_path / "codex-ca.pem"
    ca_path.write_text("codex ca\n")
    storage = tmp_path / "storage"
    supervisors: list[FakeSupervisor] = []

    def supervisor_factory() -> FakeSupervisor:
        supervisor = FakeSupervisor()
        supervisors.append(supervisor)
        return supervisor

    spawn_spec, lease = prepare_captured_run(
        CapturedRunRequest(
            client_name=CODEX_CLIENT_NAME,
            passthrough=(),
            directory=workspace,
            proxy_port=None,
            web_port=None,
            upstream="",
            storage_dir=storage,
            home_dir=source_home,
            client_bin=None,
            client_disabled=False,
            no_system_prompt=False,
            debug=False,
            web_runtime=WEB_RUNTIME_EXTERNAL,
        ),
        require_addon=lambda: addon_path,
        resolve_mitmdump=lambda: "/usr/bin/mitmdump",
        which=lambda name, *_args, **_kwargs: f"/usr/bin/{name}",
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (39223, 49223),
        inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
        user_supplied_system_prompt=lambda _args: False,
        supervisor_factory=supervisor_factory,
        proxy_starter=lambda **_kwargs: None,
        env={
            "CODEX_CA_CERTIFICATE": str(ca_path),
            "CODEX_HOME": str(source_home),
        },
    )

    try:
        assert spawn_spec.client is not None
        assert spawn_spec.managed_session is not None
        runtime_home = Path(spawn_spec.client.env["CODEX_HOME"])
        assert runtime_home != source_home
        assert runtime_home.parent == storage / "runtime-home"
        runtime_rollouts = list(runtime_home.glob("sessions/**/*.jsonl"))
        source_rollouts = list(source_home.glob("sessions/**/*.jsonl"))
        assert len(runtime_rollouts) == 1
        assert source_rollouts == []
        first_record = json.loads(runtime_rollouts[0].read_text(encoding="utf-8").splitlines()[0])
        assert first_record["payload"]["id"] == spawn_spec.managed_session.native_session_id
        assert spawn_spec.managed_session.native_session_id in spawn_spec.client.argv
    finally:
        lease.close()
