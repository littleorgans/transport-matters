"""Tests for ``manicure paths``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from manicure import __version__
from manicure.cli import WorkspaceLock, main, manifest_write, workspace_root

from ._helpers import _plain, _sample_manifest

if TYPE_CHECKING:
    import pytest

runner = CliRunner()


def test_paths_text_output_lists_expected_keys(tmp_storage: Path) -> None:
    result = runner.invoke(main, ["paths"])
    assert result.exit_code == 0
    for key in ("version", "package", "addon", "www", "storage", "rules"):
        assert key in result.stdout


def test_paths_json_is_valid_and_structured(
    tmp_storage: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default resolution: workspace storage for the current CWD.

    No live manifest → falls back to ``workspace_root(cwd)`` under the
    sandboxed ``$HOME`` that ``tmp_storage`` pins.
    """
    workdir = tmp_path / "project"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    result = runner.invoke(main, ["paths", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["version"] == __version__
    assert payload["package"].endswith("manicure")
    assert payload["addon"].endswith("addon.py")
    assert Path(payload["storage"]) == workspace_root(workdir)


def test_paths_works_with_live_lock_in_same_cwd(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``paths`` is read-only and must not touch the workspace lock."""
    monkeypatch.chdir(tmp_path)
    with WorkspaceLock(workspace_root(tmp_path)):
        result = runner.invoke(main, ["paths"])
    assert result.exit_code == 0


def test_paths_live_manifest_wins_over_default(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live manifest with a custom ``storage_dir`` overrides the default.

    When the user ran ``start --storage-dir /custom`` the manifest
    records the override; ``paths`` must surface that path, not the
    per-workspace default.
    """
    workdir = tmp_path / "project"
    workdir.mkdir()
    custom_storage = tmp_path / "custom-storage"
    custom_storage.mkdir()
    monkeypatch.chdir(workdir)
    ws_root = workspace_root(workdir)
    ws_root.mkdir(parents=True, exist_ok=True)
    manifest_write(
        ws_root / "manifest.json",
        _sample_manifest(
            workdir=workdir, storage=custom_storage, pid=12345, proxy_port=5050
        ),
    )

    with WorkspaceLock(ws_root):
        result = runner.invoke(main, ["paths", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert Path(payload["storage"]) == custom_storage


def test_paths_stale_manifest_ignored(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manifest without a live lock must not hijack resolution."""
    workdir = tmp_path / "project"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    ws_root = workspace_root(workdir)
    ws_root.mkdir(parents=True, exist_ok=True)
    manifest_write(
        ws_root / "manifest.json",
        _sample_manifest(
            workdir=workdir,
            storage=tmp_path / "stale-storage",
            pid=1,
            proxy_port=5050,
        ),
    )
    # No lock held → manifest is stale.
    result = runner.invoke(main, ["paths", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert Path(payload["storage"]) == ws_root


def test_paths_workspace_flag_accepts_directory(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--workspace /path`` resolves that path without changing CWD."""
    cwd_a = tmp_path / "a"
    cwd_a.mkdir()
    cwd_b = tmp_path / "b"
    cwd_b.mkdir()
    monkeypatch.chdir(cwd_a)
    result = runner.invoke(main, ["paths", "--workspace", str(cwd_b), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert Path(payload["storage"]) == workspace_root(cwd_b)


def test_paths_workspace_flag_accepts_slug(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--workspace slug`` finds the matching workspace via manifest scan."""
    workdir = tmp_path / "projectX"
    workdir.mkdir()
    ws_root = workspace_root(workdir)
    ws_root.mkdir(parents=True, exist_ok=True)
    manifest_write(
        ws_root / "manifest.json",
        _sample_manifest(
            workdir=workdir, storage=tmp_storage, pid=9001, proxy_port=5050
        ),
    )

    # Run from an unrelated CWD to ensure the slug lookup, not the CWD
    # fallback, is what picks the target workspace.
    other = tmp_path / "unrelated"
    other.mkdir()
    monkeypatch.chdir(other)
    # The slug matches the last segment of workdir under tmp_path.
    slug = ws_root.parent.name  # {slug} dir holds the {hash} subdir
    result = runner.invoke(main, ["paths", "--workspace", slug, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert Path(payload["storage"]) == tmp_storage


def test_paths_workspace_flag_unknown_slug_errors(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(main, ["paths", "--workspace", "no-such-slug"])
    assert result.exit_code == 2
    assert "no workspace matching" in result.output


def test_paths_help_renders() -> None:
    result = runner.invoke(main, ["paths", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--json" in output
    assert "--workspace" in output
