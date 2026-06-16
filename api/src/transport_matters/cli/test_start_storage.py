import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from transport_matters.cli import main, workspace_root
from transport_matters.launch_environment import (
    CLIENT_NAME_CLAUDE,
    build_managed_child_env,
)

from ._helpers import _which_all

if TYPE_CHECKING:
    from unittest.mock import MagicMock

runner = CliRunner()


def test_start_defaults_storage_to_per_run_root(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Without ``--storage-dir`` the child env carries the per-run root."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", "--work-dir", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    spy_run_client_children.assert_called_once()
    env = spy_run_client_children.call_args.kwargs["client"].env
    run_id = env["TRANSPORT_MATTERS_RUN_ID"]
    assert env["TRANSPORT_MATTERS_STORAGE_DIR"] == str(workspace_root(workdir) / run_id)


def test_start_same_cwd_runs_get_disjoint_storage(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Two starts in the *same* CWD resolve to distinct per-run roots."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()

    result_a = runner.invoke(main, ["claude", "--work-dir", str(workdir), "--no-system-prompt"])
    assert result_a.exit_code == 0, result_a.output
    env_a = spy_run_client_children.call_args_list[0].kwargs["client"].env

    result_b = runner.invoke(main, ["claude", "--work-dir", str(workdir), "--no-system-prompt"])
    assert result_b.exit_code == 0, result_b.output
    env_b = spy_run_client_children.call_args_list[1].kwargs["client"].env

    storage_a = env_a["TRANSPORT_MATTERS_STORAGE_DIR"]
    storage_b = env_b["TRANSPORT_MATTERS_STORAGE_DIR"]
    assert storage_a != storage_b
    # Both nest under the one shared workspace container.
    assert Path(storage_a).parent == Path(storage_b).parent == workspace_root(workdir)


def test_start_nested_session_does_not_inherit_storage_dir(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """A launch from inside an existing session must not adopt the parent's
    storage dir. ``TRANSPORT_MATTERS_STORAGE_DIR`` is inherited by managed
    children (and read by ``paths`` env-first), but it must NOT auto-populate
    a nested launch's ``--storage-dir``, or the nested run would silently
    co-reside in the parent's store once K1 removed the workspace lock.
    """
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    parent_storage = tmp_path / "parent-run"
    parent_storage.mkdir()
    monkeypatch.setenv("TRANSPORT_MATTERS_STORAGE_DIR", str(parent_storage))

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", "--work-dir", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    env = spy_run_client_children.call_args.kwargs["client"].env
    run_id = env["TRANSPORT_MATTERS_RUN_ID"]
    storage = env["TRANSPORT_MATTERS_STORAGE_DIR"]
    assert storage != str(parent_storage)
    assert storage == str(workspace_root(workdir) / run_id)


def test_start_explicit_storage_dir_overrides_workspace_root(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """``--storage-dir`` still wins over the per-workspace default."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    override = tmp_path / "override"
    override.mkdir()
    result = runner.invoke(
        main,
        [
            "claude",
            str(workdir),
            "--storage-dir",
            str(override),
            "--no-system-prompt",
        ],
    )
    assert result.exit_code == 0, result.output
    kwargs = spy_run_client_children.call_args.kwargs
    assert kwargs["client"].env["TRANSPORT_MATTERS_STORAGE_DIR"] == str(override)


def test_start_flows_working_dir_into_transport_matters_cwd_env(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """``TRANSPORT_MATTERS_CWD`` rides on the child env."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_CWD", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", "--work-dir", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    kwargs = spy_run_client_children.call_args.kwargs
    assert kwargs["client"].env["TRANSPORT_MATTERS_CWD"] == str(workdir)
    assert kwargs["mitmdump_env"]["TRANSPORT_MATTERS_CWD"] == str(workdir)


def test_start_flows_run_id_into_child_envs(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_RUN_ID", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", "--work-dir", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    kwargs = spy_run_client_children.call_args.kwargs
    claude_run_id = kwargs["client"].env["TRANSPORT_MATTERS_RUN_ID"]
    mitm_run_id = kwargs["mitmdump_env"]["TRANSPORT_MATTERS_RUN_ID"]
    assert isinstance(claude_run_id, str)
    assert claude_run_id
    assert mitm_run_id == claude_run_id


def test_start_home_dir_sets_claude_config_dir_and_manifest(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/parent/claude")
    monkeypatch.chdir(tmp_path)
    captured: dict[str, Any] = {}

    def _capture_manifest(**kwargs: Any) -> None:
        client = kwargs["client"]
        assert client is not None
        manifest_path = (
            workspace_root(client.cwd) / client.env["TRANSPORT_MATTERS_RUN_ID"] / "manifest.json"
        )
        captured["raw"] = json.loads(manifest_path.read_text(encoding="utf-8"))

    spy_run_client_children.side_effect = _capture_manifest

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(
        main,
        [
            "claude",
            str(workdir),
            "--agent-home-dir",
            "homes/claude",
            "--no-system-prompt",
        ],
    )
    assert result.exit_code == 0, result.output
    client_env = spy_run_client_children.call_args.kwargs["client"].env
    storage_dir = Path(client_env["TRANSPORT_MATTERS_STORAGE_DIR"])
    overlay_home = storage_dir / "runtime-home" / "claude"
    # --agent-home-dir is the source home; the child runs from the per-run overlay built
    # from it, so daemon background workers inherit the overlay settings-env route.
    assert client_env["CLAUDE_CONFIG_DIR"] == str(overlay_home)
    # The manifest records the same launched home the descriptor tails.
    assert captured["raw"]["home_dir"] == str(overlay_home)


def test_start_unset_home_dir_runs_from_runtime_overlay(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    # Native source home resolves to ~/.claude; pin it to a hermetic tmp home.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude").mkdir()

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", "--work-dir", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    client_env = spy_run_client_children.call_args.kwargs["client"].env
    storage_dir = Path(client_env["TRANSPORT_MATTERS_STORAGE_DIR"])
    overlay_home = storage_dir / "runtime-home" / "claude"
    # Even with no --agent-home-dir, the captured run launches from a per-run overlay
    # (source = native ~/.claude) so daemon background workers inherit the route.
    assert client_env["CLAUDE_CONFIG_DIR"] == str(overlay_home)


def test_start_print_command_home_dir_does_not_create_dir(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    home_dir = tmp_path / "claude-home"
    workdir = tmp_path / "project"
    workdir.mkdir()

    result = runner.invoke(
        main,
        [
            "claude",
            str(workdir),
            "--agent-home-dir",
            str(home_dir),
            "--no-system-prompt",
            "--print-command",
        ],
    )

    assert result.exit_code == 0, result.output
    spy_run_client_children.assert_not_called()
    assert not home_dir.exists()


def test_managed_child_home_dir_preserves_unset_and_fails_unmapped() -> None:
    base = {"CLAUDE_CONFIG_DIR": "/parent/claude"}

    assert build_managed_child_env(base)["CLAUDE_CONFIG_DIR"] == "/parent/claude"
    assert (
        build_managed_child_env(
            base,
            client_name=CLIENT_NAME_CLAUDE,
            home_dir=Path("/tmp/managed-claude"),
        )["CLAUDE_CONFIG_DIR"]
        == "/tmp/managed-claude"
    )
    with pytest.raises(ValueError, match="unmapped managed client home dir"):
        build_managed_child_env(base, client_name="unknown", home_dir=Path("/tmp/x"))


def test_start_writes_run_root_storage_into_manifest(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manifest records the per-workspace path so ``list`` surfaces it."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)

    captured: dict[str, Any] = {}

    def _fake_run_client_children(**kwargs: Any) -> None:
        client = kwargs["client"]
        run_id = client.env["TRANSPORT_MATTERS_RUN_ID"]
        manifest_path = workspace_root(client.cwd) / run_id / "manifest.json"
        captured["raw"] = json.loads(manifest_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "transport_matters.cli.runner._run_client_children",
        _fake_run_client_children,
    )

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", "--work-dir", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    run_id = captured["raw"]["run_id"]
    assert isinstance(run_id, str)
    assert run_id
    assert captured["raw"]["storage_dir"] == str(workspace_root(workdir) / run_id)


def test_start_different_cwds_get_disjoint_storage(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Two starts in different CWDs must resolve to different storage roots."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    dir_b = tmp_path / "b"
    dir_b.mkdir()

    result_a = runner.invoke(main, ["claude", "--work-dir", str(dir_a), "--no-system-prompt"])
    assert result_a.exit_code == 0, result_a.output
    env_a = spy_run_client_children.call_args_list[0].kwargs["client"].env

    result_b = runner.invoke(main, ["claude", "--work-dir", str(dir_b), "--no-system-prompt"])
    assert result_b.exit_code == 0, result_b.output
    env_b = spy_run_client_children.call_args_list[1].kwargs["client"].env

    assert env_a["TRANSPORT_MATTERS_STORAGE_DIR"] != env_b["TRANSPORT_MATTERS_STORAGE_DIR"]
    run_id_a = env_a["TRANSPORT_MATTERS_RUN_ID"]
    run_id_b = env_b["TRANSPORT_MATTERS_RUN_ID"]
    assert env_a["TRANSPORT_MATTERS_STORAGE_DIR"] == str(workspace_root(dir_a) / run_id_a)
    assert env_b["TRANSPORT_MATTERS_STORAGE_DIR"] == str(workspace_root(dir_b) / run_id_b)
