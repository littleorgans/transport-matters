import signal
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from transport_matters import env_keys
from transport_matters.captured_run import (
    CapturedRunBindConflict,
    CapturedRunProxyStartTimeout,
    CapturedRunRequest,
    build_claude_captured_invocation,
    prepare_captured_run,
)
from transport_matters.cli import BindFailure, main
from transport_matters.cli.launch_outcomes import PROXY_START_TIMEOUT_MESSAGE
from transport_matters.cli.launch_profile import ClaudeLaunchProfile
from transport_matters.cli.runner import LaunchBindFailureOutcome, LaunchExitOutcome
from transport_matters.lock import WorkspaceLock, WorkspaceLocked
from transport_matters.workspace import run_root

from ._helpers import _which_by_name

runner = CliRunner()


class FakeSupervisor:
    def __init__(self) -> None:
        self.received_signal = None
        self.spawns: list[dict[str, Any]] = []
        self.terminated = 0
        self.restored = 0
        self.installed = 0

    def install_signal_handlers(self) -> None:
        self.installed += 1

    def spawn(self, name: str, argv: list[str], **kwargs: Any) -> None:
        self.spawns.append({"name": name, "argv": argv, **kwargs})

    def terminate_all(self) -> None:
        self.terminated += 1

    def restore_signal_handlers(self) -> None:
        self.restored += 1


def _request(
    *,
    workdir: Path,
    storage: Path,
    addon: Path,
    proxy_port: int | None = 9900,
    web_port: int | None = 9901,
) -> CapturedRunRequest:
    addon.write_text("# test addon\n", encoding="utf-8")
    return CapturedRunRequest(
        client_name="claude",
        passthrough=(),
        directory=workdir,
        proxy_port=proxy_port,
        web_port=web_port,
        upstream="https://api.anthropic.com",
        storage_dir=storage,
        home_dir=None,
        client_bin=None,
        client_disabled=False,
        no_system_prompt=True,
        debug=False,
    )


def _prepare(
    *,
    request: CapturedRunRequest,
    addon: Path,
    supervisor: FakeSupervisor,
) -> Any:
    return prepare_captured_run(
        request,
        require_addon=lambda: addon,
        resolve_mitmdump=lambda: "/bin/mitmdump",
        which=_which_by_name({"claude": "/bin/claude"}),
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (request.proxy_port or 9900, request.web_port or 9901),
        inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
        user_supplied_system_prompt=lambda _passthrough: False,
        supervisor_factory=lambda: supervisor,
        proxy_starter=lambda **_kwargs: None,
    )


@pytest.mark.parametrize(
    "module",
    [
        "transport_matters.captured_run",
        "transport_matters.captured_claude",
        "transport_matters.captured_codex",
        "transport_matters.captured_run_context",
    ],
)
def test_captured_run_modules_are_standalone_importable(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_prepare_captured_run_spawn_spec_matches_public_invocation_helper(
    tmp_storage: Path,
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    addon = tmp_path / "addon.py"
    supervisor = FakeSupervisor()
    proxy_calls: list[dict[str, Any]] = []

    def _proxy_starter(**kwargs: Any) -> None:
        proxy_calls.append(kwargs)

    spawn_spec, lease = prepare_captured_run(
        _request(workdir=workdir, storage=tmp_storage, addon=addon),
        require_addon=lambda: addon,
        resolve_mitmdump=lambda: "/bin/mitmdump",
        which=_which_by_name({"claude": "/bin/claude"}),
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (9900, 9901),
        inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
        user_supplied_system_prompt=lambda _passthrough: False,
        supervisor_factory=lambda: supervisor,
        proxy_starter=_proxy_starter,
    )
    try:
        # prepare_captured_run builds a per-run overlay and launches Claude from it
        # (CLAUDE_CONFIG_DIR=overlay). A native launch (home_dir=None) does not publish
        # AGENT_HOME_DIR onto the launch env, so the public helper mirrors with home_dir=None
        # and the same overlay to produce an identical spawn spec.
        assert spawn_spec.client is not None
        assert env_keys.AGENT_HOME_DIR not in spawn_spec.launch_env
        overlay_home = Path(spawn_spec.client.env["CLAUDE_CONFIG_DIR"])
        expected = build_claude_captured_invocation(
            addon_path=addon,
            mitmdump="/bin/mitmdump",
            upstream="https://api.anthropic.com",
            working_dir=workdir,
            resolved_storage=tmp_storage,
            run_id=spawn_spec.run_id,
            home_dir=None,
            claude_path="/bin/claude",
            claude_passthrough_user=(),
            no_claude=False,
            no_system_prompt=True,
            debug=False,
            profile=ClaudeLaunchProfile(),
            managed_session=spawn_spec.managed_session,
            inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
            user_supplied_system_prompt=lambda _passthrough: False,
            runtime_home_dir=overlay_home,
        )
        expected_argv, expected_env, expected_client = expected(9900, 9901)

        assert proxy_calls[0]["mitmdump_argv"] == expected_argv
        assert proxy_calls[0]["mitmdump_env"] == expected_env
        assert spawn_spec.launch_env == expected_env
        assert spawn_spec.client == expected_client
        assert spawn_spec.client is not None
        assert spawn_spec.client.cwd == workdir
    finally:
        lease.close()


def test_prepare_captured_run_lease_close_removes_manifest_and_releases_lock(
    tmp_storage: Path,
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    addon = tmp_path / "addon.py"
    supervisor = FakeSupervisor()

    spawn_spec, lease = _prepare(
        request=_request(workdir=workdir, storage=tmp_storage, addon=addon),
        addon=addon,
        supervisor=supervisor,
    )
    run_dir = run_root(workdir, spawn_spec.run_id)
    manifest_path = run_dir / "manifest.json"

    assert manifest_path.exists()
    with pytest.raises(WorkspaceLocked), WorkspaceLock(run_dir):
        pass

    lease.close()

    assert not manifest_path.exists()
    with WorkspaceLock(run_dir):
        pass
    assert supervisor.terminated == 1
    assert supervisor.restored == 1


def test_prepare_captured_run_preserves_owned_session_across_retries(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    addon = tmp_path / "addon.py"
    request = _request(
        workdir=workdir,
        storage=tmp_storage,
        addon=addon,
        proxy_port=None,
        web_port=None,
    )
    pairs = iter([(54321, 54322), (60001, 60002)])

    def _alloc() -> tuple[int, int]:
        return next(pairs)

    monkeypatch.setattr("transport_matters.cli.bind_failure.allocate_port_pair", _alloc)
    attempts: list[dict[str, Any]] = []
    supervisors = [FakeSupervisor(), FakeSupervisor()]

    def _proxy_starter(**kwargs: Any) -> Any:
        attempts.append(kwargs)
        if len(attempts) == 1:
            return LaunchBindFailureOutcome(
                BindFailure(
                    proxy_port=kwargs["proxy_port"],
                    web_port=kwargs["web_port"],
                    failing_ports=(),
                    log_path=tmp_path / "mitmdump.log",
                )
            )
        return None

    spawn_spec, lease = prepare_captured_run(
        request,
        require_addon=lambda: addon,
        resolve_mitmdump=lambda: "/bin/mitmdump",
        which=_which_by_name({"claude": "/bin/claude"}),
        port_in_use=lambda _port: False,
        allocate_port_pair=_alloc,
        inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
        user_supplied_system_prompt=lambda _passthrough: False,
        supervisor_factory=lambda: supervisors.pop(0),
        proxy_starter=_proxy_starter,
    )
    try:
        first_env = attempts[0]["mitmdump_env"]
        second_env = attempts[1]["mitmdump_env"]
        assert attempts[0]["proxy_port"] == 54321
        assert attempts[1]["proxy_port"] == 60001
        assert first_env[env_keys.RUN_ID] == second_env[env_keys.RUN_ID] == spawn_spec.run_id
        assert (
            first_env[env_keys.OWNED_NATIVE_SESSION_ID]
            == second_env[env_keys.OWNED_NATIVE_SESSION_ID]
        )
        assert (
            first_env[env_keys.OWNED_SOURCE_DESCRIPTOR]
            == second_env[env_keys.OWNED_SOURCE_DESCRIPTOR]
        )
        assert len(attempts) == 2
    finally:
        lease.close()


def test_prepare_captured_run_retries_proxy_start_timeout_with_fresh_ports(
    tmp_storage: Path,
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    addon = tmp_path / "addon.py"
    request = _request(
        workdir=workdir,
        storage=tmp_storage,
        addon=addon,
        proxy_port=None,
        web_port=None,
    )
    pairs = iter([(54321, 54322), (60001, 60002), (61001, 61002)])
    attempts: list[dict[str, Any]] = []
    sleeps: list[float] = []
    supervisors = [FakeSupervisor(), FakeSupervisor(), FakeSupervisor()]

    def _proxy_starter(**kwargs: Any) -> Any:
        attempts.append(kwargs)
        return LaunchExitOutcome(exit_code=1, error=PROXY_START_TIMEOUT_MESSAGE)

    with pytest.raises(CapturedRunProxyStartTimeout):
        prepare_captured_run(
            request,
            require_addon=lambda: addon,
            resolve_mitmdump=lambda: "/bin/mitmdump",
            which=_which_by_name({"claude": "/bin/claude"}),
            port_in_use=lambda _port: False,
            allocate_port_pair=lambda: next(pairs),
            inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
            user_supplied_system_prompt=lambda _passthrough: False,
            supervisor_factory=lambda: supervisors.pop(0),
            proxy_starter=_proxy_starter,
            readiness_timeout_sleep=sleeps.append,
            readiness_timeout_jitter=lambda: 0.0,
        )

    assert [attempt["proxy_port"] for attempt in attempts] == [54321, 60001, 61001]
    assert len(sleeps) == 2


def test_prepare_captured_run_raises_latest_timeout_after_prior_bind_failure(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    addon = tmp_path / "addon.py"
    request = _request(
        workdir=workdir,
        storage=tmp_storage,
        addon=addon,
        proxy_port=None,
        web_port=None,
    )
    pairs = iter([(54321, 54322), (60001, 60002), (61001, 61002)])
    monkeypatch.setattr(
        "transport_matters.cli.bind_failure.allocate_port_pair", lambda: next(pairs)
    )
    attempts: list[dict[str, Any]] = []
    sleeps: list[float] = []
    supervisors = [FakeSupervisor(), FakeSupervisor(), FakeSupervisor()]

    def _proxy_starter(**kwargs: Any) -> Any:
        attempts.append(kwargs)
        if len(attempts) == 1:
            return LaunchBindFailureOutcome(
                BindFailure(
                    proxy_port=kwargs["proxy_port"],
                    web_port=kwargs["web_port"],
                    failing_ports=(),
                    log_path=tmp_path / "mitmdump.log",
                )
            )
        return LaunchExitOutcome(exit_code=1, error=PROXY_START_TIMEOUT_MESSAGE)

    with pytest.raises(CapturedRunProxyStartTimeout):
        prepare_captured_run(
            request,
            require_addon=lambda: addon,
            resolve_mitmdump=lambda: "/bin/mitmdump",
            which=_which_by_name({"claude": "/bin/claude"}),
            port_in_use=lambda _port: False,
            allocate_port_pair=lambda: next(pairs),
            inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
            user_supplied_system_prompt=lambda _passthrough: False,
            supervisor_factory=lambda: supervisors.pop(0),
            proxy_starter=_proxy_starter,
            readiness_timeout_sleep=sleeps.append,
            readiness_timeout_jitter=lambda: 0.0,
        )

    assert [attempt["proxy_port"] for attempt in attempts] == [54321, 60001, 61001]
    assert len(sleeps) == 1


def test_prepare_captured_run_raises_latest_bind_after_prior_timeout(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    addon = tmp_path / "addon.py"
    request = _request(
        workdir=workdir,
        storage=tmp_storage,
        addon=addon,
        proxy_port=None,
        web_port=None,
    )
    pairs = iter([(54321, 54322), (60001, 60002), (61001, 61002)])
    monkeypatch.setattr(
        "transport_matters.cli.bind_failure.allocate_port_pair", lambda: next(pairs)
    )
    attempts: list[dict[str, Any]] = []
    supervisors = [FakeSupervisor(), FakeSupervisor(), FakeSupervisor()]

    def _proxy_starter(**kwargs: Any) -> Any:
        attempts.append(kwargs)
        if len(attempts) == 1:
            return LaunchExitOutcome(exit_code=1, error=PROXY_START_TIMEOUT_MESSAGE)
        return LaunchBindFailureOutcome(
            BindFailure(
                proxy_port=kwargs["proxy_port"],
                web_port=kwargs["web_port"],
                failing_ports=(),
                log_path=tmp_path / "mitmdump.log",
            )
        )

    with pytest.raises(CapturedRunBindConflict):
        prepare_captured_run(
            request,
            require_addon=lambda: addon,
            resolve_mitmdump=lambda: "/bin/mitmdump",
            which=_which_by_name({"claude": "/bin/claude"}),
            port_in_use=lambda _port: False,
            allocate_port_pair=lambda: next(pairs),
            inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
            user_supplied_system_prompt=lambda _passthrough: False,
            supervisor_factory=lambda: supervisors.pop(0),
            proxy_starter=_proxy_starter,
            readiness_timeout_sleep=lambda _delay: None,
            readiness_timeout_jitter=lambda: 0.0,
        )

    assert [attempt["proxy_port"] for attempt in attempts] == [54321, 60001, 61001]


def test_captured_run_c1_keeps_print_command_dry_run_unchanged(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--no-system-prompt", "--print-command"])

    assert result.exit_code == 0, result.output
    assert "/bin/mitmdump" in result.stdout
    assert "/bin/claude" in result.stdout
    assert "--session-id" in result.stdout
    spy_run_client_children.assert_not_called()


def test_rewired_cli_bails_out_on_signal_before_claude_spawn(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sup = MagicMock()
    fake_sup.received_signal = int(signal.SIGINT)
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.setattr("transport_matters.cli.runner.ProcessSupervisor", lambda: fake_sup)
    monkeypatch.setattr("transport_matters.cli.runner.wait_for_port_ready", lambda *_a, **_k: True)

    result = runner.invoke(main, ["claude", "--no-system-prompt"])

    assert result.exit_code == 0, result.output
    spawn_names = [call.args[0] for call in fake_sup.spawn.call_args_list]
    assert spawn_names == ["mitmdump"]
    fake_sup.terminate_all.assert_called_once()
    fake_sup.wait_any.assert_not_called()
