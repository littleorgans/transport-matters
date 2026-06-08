from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from transport_matters import env_keys
from transport_matters.captured_run import (
    CapturedRunRequest,
    build_start_invocation,
    prepare_captured_run,
)
from transport_matters.cli import BindFailure, main
from transport_matters.cli.launch_profile import ClaudeLaunchProfile
from transport_matters.lock import WorkspaceLock, WorkspaceLocked
from transport_matters.workspace import run_root

from ._helpers import _patch_allocate_pairs, _which_by_name

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

runner = CliRunner()


class FakeSupervisor:
    def __init__(self) -> None:
        self.received_signal = None
        self.spawns: list[dict[str, Any]] = []
        self.terminated = 0
        self.restored = 0

    def spawn(self, name: str, argv: list[str], **kwargs: Any) -> None:
        self.spawns.append({"name": name, "argv": argv, **kwargs})

    def terminate_all(self) -> None:
        self.terminated += 1

    def restore_signal_handlers(self) -> None:
        self.restored += 1


def _request(*, workdir: Path, storage: Path, addon: Path) -> CapturedRunRequest:
    addon.write_text("# test addon\n", encoding="utf-8")
    return CapturedRunRequest(
        client_name="claude",
        passthrough=(),
        directory=workdir,
        proxy_port=9900,
        web_port=9901,
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
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    monkeypatch.setattr("transport_matters.cli.runner.wait_for_port_ready", lambda *_a: True)
    return prepare_captured_run(
        request,
        require_addon=lambda: addon,
        resolve_mitmdump=lambda: "/bin/mitmdump",
        which=_which_by_name({"claude": "/bin/claude"}),
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (request.proxy_port or 9900, request.web_port or 9901),
        inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
        user_supplied_system_prompt=lambda _passthrough: False,
        supervisor_factory=lambda: supervisor,  # type: ignore[arg-type, return-value]
    )


def test_prepare_captured_run_spawn_spec_matches_public_invocation_helper(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    addon = tmp_path / "addon.py"
    supervisor = FakeSupervisor()

    spawn_spec, lease = _prepare(
        request=_request(workdir=workdir, storage=tmp_storage, addon=addon),
        addon=addon,
        supervisor=supervisor,
        monkeypatch=monkeypatch,
    )
    try:
        expected = build_start_invocation(
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
        )
        expected_argv, expected_env, expected_client = expected(9900, 9901)

        assert supervisor.spawns[0]["name"] == "mitmdump"
        assert supervisor.spawns[0]["argv"] == expected_argv
        assert supervisor.spawns[0]["env"] == {**expected_env, "PYTHONUNBUFFERED": "1"}
        assert spawn_spec.launch_env == expected_env
        assert spawn_spec.client == expected_client
        assert spawn_spec.client is not None
        assert spawn_spec.client.cwd == workdir
    finally:
        lease.close()


def test_prepare_captured_run_lease_close_removes_manifest_and_releases_lock(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    addon = tmp_path / "addon.py"
    supervisor = FakeSupervisor()

    spawn_spec, lease = _prepare(
        request=_request(workdir=workdir, storage=tmp_storage, addon=addon),
        addon=addon,
        supervisor=supervisor,
        monkeypatch=monkeypatch,
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


def test_owned_session_is_preserved_across_bind_retry(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    _patch_allocate_pairs(monkeypatch, [(54321, 54322), (60001, 60002)])
    log_path = tmp_path / "mitmdump.log"

    def _side_effect(**kwargs: Any) -> None:
        if spy_run_client_children.call_count == 1:
            raise BindFailure(
                proxy_port=kwargs["proxy_port"],
                web_port=kwargs["web_port"],
                failing_ports=(),
                log_path=log_path,
            )

    spy_run_client_children.side_effect = _side_effect

    result = runner.invoke(main, ["claude"])

    assert result.exit_code == 0, result.output
    first_env = spy_run_client_children.call_args_list[0].kwargs["mitmdump_env"]
    second_env = spy_run_client_children.call_args_list[1].kwargs["mitmdump_env"]
    assert (
        first_env[env_keys.OWNED_NATIVE_SESSION_ID] == second_env[env_keys.OWNED_NATIVE_SESSION_ID]
    )
    assert (
        first_env[env_keys.OWNED_SOURCE_DESCRIPTOR] == second_env[env_keys.OWNED_SOURCE_DESCRIPTOR]
    )
    assert spy_run_client_children.call_count == 2


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
