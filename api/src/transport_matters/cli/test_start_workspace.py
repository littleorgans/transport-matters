from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from transport_matters.cli import (
    WorkspaceLock,
    main,
    manifest_write,
    workspace_id,
    workspace_root,
)

from ._helpers import _sample_manifest, _which_all

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

    import pytest

runner = CliRunner()


def test_start_fails_fast_when_workspace_locked(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Second ``start`` in the same CWD must exit 2 and surface live state."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    ws_root = workspace_root(workdir)
    ws_root.mkdir(parents=True, exist_ok=True)
    manifest_write(
        ws_root / "manifest.json",
        _sample_manifest(
            workdir=workdir, storage=tmp_storage, pid=99999, proxy_port=4545
        ),
    )

    with WorkspaceLock(ws_root):
        result = runner.invoke(main, ["claude", str(workdir)])

    assert result.exit_code == 2
    assert "already live" in result.output
    assert "99999" in result.output
    assert "4545" in result.output
    assert "8788" in result.output
    spy_run_client_children.assert_not_called()


def test_start_contention_message_falls_back_when_manifest_missing(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Lock held but no sibling manifest still exits 2 cleanly."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    ws_root = workspace_root(workdir)

    with WorkspaceLock(ws_root):
        result = runner.invoke(main, ["claude", str(workdir)])

    assert result.exit_code == 2
    assert "lock" in result.output.lower()
    spy_run_client_children.assert_not_called()


def test_start_writes_manifest_visible_to_client_runner(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While the shared runner is running the manifest must exist on disk."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    captured: dict[str, Any] = {}

    def _fake_run_client_children(**kwargs: Any) -> None:
        cwd = kwargs["client"].cwd
        manifest_path = workspace_root(cwd) / "manifest.json"
        captured["exists_mid_run"] = manifest_path.exists()
        captured["raw"] = json.loads(manifest_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "transport_matters.cli.runner._run_client_children",
        _fake_run_client_children,
    )

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(
        main, ["claude", str(workdir), "--proxy-port", "9123", "--web-port", "9124"]
    )
    assert result.exit_code == 0, result.output
    assert captured["exists_mid_run"] is True
    raw = captured["raw"]
    assert raw["cwd"] == str(workdir)
    assert raw["proxy_port"] == 9123
    assert raw["web_port"] == 9124
    assert isinstance(raw["run_id"], str)
    assert raw["run_id"]
    assert raw["pid"] > 0
    assert raw["slug"] == workspace_id(workdir).slug
    assert raw["hash"] == workspace_id(workdir).hash


def test_start_releases_lock_on_normal_exit(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """After a successful ``start``, the lock must release."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result_a = runner.invoke(main, ["claude", str(workdir)])
    assert result_a.exit_code == 0, result_a.output
    assert not (workspace_root(workdir) / "manifest.json").exists()
    with WorkspaceLock(workspace_root(workdir)):
        pass
    result_b = runner.invoke(main, ["claude", str(workdir)])
    assert result_b.exit_code == 0, result_b.output
    assert spy_run_client_children.call_count == 2


def test_start_different_cwds_coexist(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Two ``start``s in different CWDs must not contend on the lock."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    dir_b = tmp_path / "b"
    dir_b.mkdir()

    with WorkspaceLock(workspace_root(dir_a)):
        result = runner.invoke(main, ["claude", str(dir_b)])
    assert result.exit_code == 0, result.output
