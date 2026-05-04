"""Tests for ``manicure list``.

The list body lives in ``cli/instances.py``. It scans
``~/.transport-matters/workspaces/`` for manifests and probes each one's lock to
distinguish live instances from stale manifests, transparently reaping
the latter.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from transport_matters.cli import WorkspaceLock, main, manifest_write, workspace_root

from ._helpers import _plain, _sample_manifest

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_list_empty_prints_friendly_message(tmp_storage: Path) -> None:
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "no live Transport Matters instances" in result.output


def test_list_shows_live_instance(tmp_storage: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    ws_root = workspace_root(workdir)
    ws_root.mkdir(parents=True, exist_ok=True)
    m = _sample_manifest(
        workdir=workdir, storage=tmp_storage, pid=11111, proxy_port=9000, web_port=9001
    )
    manifest_write(ws_root / "manifest.json", m)

    with WorkspaceLock(ws_root):
        result = runner.invoke(main, ["list"])

    assert result.exit_code == 0, result.output
    assert "11111" in result.output
    assert "9000" in result.output
    assert "9001" in result.output
    assert m.slug in result.output


def test_list_reaps_stale_manifest(tmp_storage: Path, tmp_path: Path) -> None:
    """A manifest whose lock isn't held → transparently removed on list."""
    workdir = tmp_path / "project"
    workdir.mkdir()
    ws_root = workspace_root(workdir)
    ws_root.mkdir(parents=True, exist_ok=True)
    manifest_path = ws_root / "manifest.json"
    manifest_write(
        manifest_path,
        _sample_manifest(workdir=workdir, storage=tmp_storage, pid=22222),
    )
    # No lock held — manifest is stale.

    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "22222" not in result.output
    assert "no live Transport Matters instances" in result.output
    assert not manifest_path.exists()


def test_list_reap_leaves_lock_file_in_place(tmp_storage: Path, tmp_path: Path) -> None:
    """Regression: reap must NOT unlink the lock file.

    If ``_reap`` unlinked ``lock`` while process A held the flock on
    that inode, a subsequent ``start`` (process C) would open the path
    with ``O_CREAT``, land on a fresh inode, flock it successfully, and
    end up co-resident with A on the same workspace. Leaving the empty
    lock file alone keeps inode identity across reaps so the next
    ``flock`` acquisition is correctly serialised.
    """
    workdir = tmp_path / "project"
    workdir.mkdir()
    ws_root = workspace_root(workdir)
    ws_root.mkdir(parents=True, exist_ok=True)
    manifest_path = ws_root / "manifest.json"
    lock_path = ws_root / "lock"
    manifest_write(
        manifest_path,
        _sample_manifest(workdir=workdir, storage=tmp_storage, pid=22222),
    )
    # Create the lock file so we can observe its inode — do NOT hold it.
    lock_path.touch()
    inode_before = lock_path.stat().st_ino

    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert not manifest_path.exists()
    assert lock_path.exists()
    assert lock_path.stat().st_ino == inode_before


def test_list_json_returns_live_instances(tmp_storage: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    ws_root = workspace_root(workdir)
    ws_root.mkdir(parents=True, exist_ok=True)
    manifest_write(
        ws_root / "manifest.json",
        _sample_manifest(
            workdir=workdir,
            storage=tmp_storage,
            pid=33333,
            proxy_port=7000,
            web_port=7001,
        ),
    )

    with WorkspaceLock(ws_root):
        result = runner.invoke(main, ["list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 1
    entry = payload[0]
    assert entry["pid"] == 33333
    assert entry["proxy_port"] == 7000
    assert entry["web_port"] == 7001
    assert entry["cwd"] == str(workdir)


def test_list_json_empty_is_empty_array(tmp_storage: Path) -> None:
    result = runner.invoke(main, ["list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_list_help_is_plain_text() -> None:
    result = runner.invoke(main, ["list", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "List live Transport Matters instances" in output
    assert "--json" in output
