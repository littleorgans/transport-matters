from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from transport_matters.cli import main, workspace_root

from ._helpers import _which_all

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    import pytest

runner = CliRunner()


def test_start_defaults_storage_to_per_run_root(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Without ``--storage-dir`` the child env carries the per-run root."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", str(workdir), "--no-system-prompt"])
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
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()

    result_a = runner.invoke(main, ["claude", str(workdir), "--no-system-prompt"])
    assert result_a.exit_code == 0, result_a.output
    env_a = spy_run_client_children.call_args_list[0].kwargs["client"].env

    result_b = runner.invoke(main, ["claude", str(workdir), "--no-system-prompt"])
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
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    parent_storage = tmp_path / "parent-run"
    parent_storage.mkdir()
    monkeypatch.setenv("TRANSPORT_MATTERS_STORAGE_DIR", str(parent_storage))

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", str(workdir), "--no-system-prompt"])
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
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

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
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_CWD", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", str(workdir), "--no-system-prompt"])
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
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_RUN_ID", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    kwargs = spy_run_client_children.call_args.kwargs
    claude_run_id = kwargs["client"].env["TRANSPORT_MATTERS_RUN_ID"]
    mitm_run_id = kwargs["mitmdump_env"]["TRANSPORT_MATTERS_RUN_ID"]
    assert isinstance(claude_run_id, str)
    assert claude_run_id
    assert mitm_run_id == claude_run_id


def test_start_writes_workspace_storage_into_manifest(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manifest records the per-workspace path so ``list`` surfaces it."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
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
    result = runner.invoke(main, ["claude", str(workdir), "--no-system-prompt"])
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
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    dir_b = tmp_path / "b"
    dir_b.mkdir()

    result_a = runner.invoke(main, ["claude", str(dir_a), "--no-system-prompt"])
    assert result_a.exit_code == 0, result_a.output
    env_a = spy_run_client_children.call_args_list[0].kwargs["client"].env

    result_b = runner.invoke(main, ["claude", str(dir_b), "--no-system-prompt"])
    assert result_b.exit_code == 0, result_b.output
    env_b = spy_run_client_children.call_args_list[1].kwargs["client"].env

    assert (
        env_a["TRANSPORT_MATTERS_STORAGE_DIR"] != env_b["TRANSPORT_MATTERS_STORAGE_DIR"]
    )
    run_id_a = env_a["TRANSPORT_MATTERS_RUN_ID"]
    run_id_b = env_b["TRANSPORT_MATTERS_RUN_ID"]
    assert env_a["TRANSPORT_MATTERS_STORAGE_DIR"] == str(
        workspace_root(dir_a) / run_id_a
    )
    assert env_b["TRANSPORT_MATTERS_STORAGE_DIR"] == str(
        workspace_root(dir_b) / run_id_b
    )
