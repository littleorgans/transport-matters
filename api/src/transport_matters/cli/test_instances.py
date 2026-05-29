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

from transport_matters.cli import WorkspaceLock, main

from ._helpers import _plain, _sample_manifest, _write_run_manifest

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
    m = _sample_manifest(
        workdir=workdir, storage=tmp_storage, pid=11111, proxy_port=9000, web_port=9001
    )
    run_dir = _write_run_manifest(workdir, m)

    with WorkspaceLock(run_dir):
        result = runner.invoke(main, ["list"])

    assert result.exit_code == 0, result.output
    assert "11111" in result.output
    assert "9000" in result.output
    assert "9001" in result.output
    assert m.slug in result.output
    assert m.run_id[:8] in result.output


def test_list_shows_multiple_runs_in_one_cwd(tmp_storage: Path, tmp_path: Path) -> None:
    """K1: two live runs in one CWD are listed separately."""
    workdir = tmp_path / "project"
    workdir.mkdir()
    m1 = _write_run_manifest(
        workdir,
        _sample_manifest(workdir=workdir, storage=tmp_storage, pid=11111, run_id="r1"),
    )
    m2 = _write_run_manifest(
        workdir,
        _sample_manifest(workdir=workdir, storage=tmp_storage, pid=22222, run_id="r2"),
    )

    with WorkspaceLock(m1), WorkspaceLock(m2):
        result = runner.invoke(main, ["list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {entry["pid"] for entry in payload} == {11111, 22222}
    assert {entry["run_id"] for entry in payload} == {"r1", "r2"}


def test_list_reaps_stale_manifest(tmp_storage: Path, tmp_path: Path) -> None:
    """A manifest whose lock isn't held → transparently removed on list."""
    workdir = tmp_path / "project"
    workdir.mkdir()
    run_dir = _write_run_manifest(
        workdir,
        _sample_manifest(workdir=workdir, storage=tmp_storage, pid=22222),
    )
    manifest_path = run_dir / "manifest.json"
    # No lock held — manifest is stale.

    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "22222" not in result.output
    assert "no live Transport Matters instances" in result.output
    assert not manifest_path.exists()


def test_list_reap_leaves_lock_file_in_place(tmp_storage: Path, tmp_path: Path) -> None:
    """Reap removes only the manifest, never the lock file.

    The run directory also holds captured history, and the lock file is
    cheap and harmless to keep. No future ``start`` reuses this run's
    directory (each launch mints a fresh ``run_id``), so the old
    inode-reuse race that motivated leaving the lock in place cannot
    occur — but unlinking it would still be pointless churn.
    """
    workdir = tmp_path / "project"
    workdir.mkdir()
    run_dir = _write_run_manifest(
        workdir,
        _sample_manifest(workdir=workdir, storage=tmp_storage, pid=22222),
    )
    manifest_path = run_dir / "manifest.json"
    lock_path = run_dir / "lock"
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
    run_dir = _write_run_manifest(
        workdir,
        _sample_manifest(
            workdir=workdir,
            storage=tmp_storage,
            pid=33333,
            proxy_port=7000,
            web_port=7001,
        ),
    )

    with WorkspaceLock(run_dir):
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
    assert entry["run_id"] == "run-001"


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
