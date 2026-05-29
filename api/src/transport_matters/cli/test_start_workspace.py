from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from transport_matters.cli import (
    WorkspaceLock,
    main,
    run_root,
    workspace_id,
    workspace_root,
)

from ._helpers import _which_all

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

    import pytest

runner = CliRunner()


def test_start_coexists_with_live_sibling_run(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """A second ``start`` in the same CWD launches alongside a live sibling.

    K1: the lock is per-run, not per-workspace. Holding a sibling run's
    lock (a live instance) must not block a fresh launch, which mints its
    own ``run_id`` and its own lock.
    """
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    sibling = run_root(workdir, "00000000-0000-0000-0000-000000000000")

    with WorkspaceLock(sibling):
        result = runner.invoke(main, ["claude", str(workdir), "--no-system-prompt"])

    assert result.exit_code == 0, result.output
    spy_run_client_children.assert_called_once()


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
        client = kwargs["client"]
        run_id = client.env["TRANSPORT_MATTERS_RUN_ID"]
        manifest_path = workspace_root(client.cwd) / run_id / "manifest.json"
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


def test_start_reaps_its_run_manifest_on_normal_exit(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """After a successful ``start`` the run's manifest is unlinked.

    No live advertisement lingers under the workspace container, and the
    same CWD can launch again.
    """
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result_a = runner.invoke(main, ["claude", str(workdir)])
    assert result_a.exit_code == 0, result_a.output
    assert list(workspace_root(workdir).glob("*/manifest.json")) == []
    result_b = runner.invoke(main, ["claude", str(workdir)])
    assert result_b.exit_code == 0, result_b.output
    assert spy_run_client_children.call_count == 2


def test_start_different_cwds_coexist(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Starts in different CWDs each launch independently."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    dir_b = tmp_path / "b"
    dir_b.mkdir()

    assert runner.invoke(main, ["claude", str(dir_a)]).exit_code == 0
    assert runner.invoke(main, ["claude", str(dir_b)]).exit_code == 0
    assert spy_run_client_children.call_count == 2
