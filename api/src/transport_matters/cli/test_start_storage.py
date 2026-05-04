from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from transport_matters.cli import main, workspace_root
from transport_matters.workspace import workspace_storage

from ._helpers import _which_all

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

    import pytest

runner = CliRunner()


def test_start_defaults_storage_to_workspace_root(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Without ``--storage-dir`` the child env carries the workspace root."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("MANICURE_STORAGE_DIR", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["start", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    spy_run_children.assert_called_once()
    kwargs = spy_run_children.call_args.kwargs
    expected = workspace_storage(workdir)
    assert kwargs["claude_env"]["MANICURE_STORAGE_DIR"] == str(expected)


def test_start_explicit_storage_dir_overrides_workspace_root(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
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
            "start",
            str(workdir),
            "--storage-dir",
            str(override),
            "--no-system-prompt",
        ],
    )
    assert result.exit_code == 0, result.output
    kwargs = spy_run_children.call_args.kwargs
    assert kwargs["claude_env"]["MANICURE_STORAGE_DIR"] == str(override)


def test_start_flows_working_dir_into_manicure_cwd_env(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """``MANICURE_CWD`` rides on the child env."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("MANICURE_CWD", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["start", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    kwargs = spy_run_children.call_args.kwargs
    assert kwargs["claude_env"]["MANICURE_CWD"] == str(workdir)
    assert kwargs["mitmdump_env"]["MANICURE_CWD"] == str(workdir)


def test_start_flows_run_id_into_child_envs(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("MANICURE_RUN_ID", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["start", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    kwargs = spy_run_children.call_args.kwargs
    claude_run_id = kwargs["claude_env"]["MANICURE_RUN_ID"]
    mitm_run_id = kwargs["mitmdump_env"]["MANICURE_RUN_ID"]
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
    monkeypatch.delenv("MANICURE_STORAGE_DIR", raising=False)

    captured: dict[str, Any] = {}

    def _fake_run_children(**kwargs: Any) -> None:
        cwd = kwargs["claude_cwd"]
        manifest_path = workspace_root(cwd) / "manifest.json"
        captured["raw"] = json.loads(manifest_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "transport_matters.cli.runner._run_children", _fake_run_children
    )

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["start", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    assert captured["raw"]["storage_dir"] == str(workspace_storage(workdir))
    assert isinstance(captured["raw"]["run_id"], str)
    assert captured["raw"]["run_id"]


def test_start_different_cwds_get_disjoint_storage(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Two starts in different CWDs must resolve to different storage roots."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("MANICURE_STORAGE_DIR", raising=False)

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    dir_b = tmp_path / "b"
    dir_b.mkdir()

    result_a = runner.invoke(main, ["start", str(dir_a), "--no-system-prompt"])
    assert result_a.exit_code == 0, result_a.output
    env_a = spy_run_children.call_args_list[0].kwargs["claude_env"]

    result_b = runner.invoke(main, ["start", str(dir_b), "--no-system-prompt"])
    assert result_b.exit_code == 0, result_b.output
    env_b = spy_run_children.call_args_list[1].kwargs["claude_env"]

    assert env_a["MANICURE_STORAGE_DIR"] != env_b["MANICURE_STORAGE_DIR"]
    assert env_a["MANICURE_STORAGE_DIR"] == str(workspace_storage(dir_a))
    assert env_b["MANICURE_STORAGE_DIR"] == str(workspace_storage(dir_b))
