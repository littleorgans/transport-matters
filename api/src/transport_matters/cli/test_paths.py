"""Tests for ``transport-matters paths``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from transport_matters.cli import WorkspaceLock, main, workspace_root

from ._helpers import _plain, _sample_manifest, _write_run_manifest

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_transport_matters_cwd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests that rely on the Path.cwd() fallback must not inherit a
    # TRANSPORT_MATTERS_CWD from the shell running pytest (e.g. a Claude session
    # launched by ``transport-matters claude``). Clear unconditionally; tests that
    # want the env-set branch can set it themselves.
    monkeypatch.delenv("TRANSPORT_MATTERS_CWD", raising=False)


def test_paths_text_output_lists_expected_keys(tmp_storage: Path) -> None:
    result = runner.invoke(main, ["paths"])
    assert result.exit_code == 0
    for key in ("version", "package", "addon", "www", "storage", "rules"):
        assert key in result.stdout


def test_paths_prefers_storage_dir_env(
    tmp_storage: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inside a launched session, ``paths`` reports the env's storage dir.

    A run launched by ``transport-matters claude`` carries its own
    per-run storage dir in ``TRANSPORT_MATTERS_STORAGE_DIR``; ``paths``
    must report it verbatim, unambiguous even when sibling runs share the
    CWD.
    """
    run_storage = tmp_path / "ws" / "hash" / "run-xyz"
    monkeypatch.setenv("TRANSPORT_MATTERS_STORAGE_DIR", str(run_storage))
    result = runner.invoke(main, ["paths", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert Path(payload["storage"]) == run_storage


def test_paths_errors_without_env_or_live_run(
    tmp_storage: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default resolution fails loudly when no run identifies a storage dir.

    After per-run storage, the workspace container is not itself a storage dir.
    A bare shell must not render empty ``exchanges`` / ``rules`` paths.
    """
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)
    workdir = tmp_path / "project"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    result = runner.invoke(main, ["paths", "--json"])
    assert result.exit_code == 2
    assert "no live Transport Matters instance" in result.output
    assert "run transport-matters list" in result.output
    assert "--workspace <slug-or-storage-dir>" in result.output
    assert result.stdout == ""


def test_paths_works_with_live_lock_in_same_cwd(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``paths`` is read-only and must not touch a run's lock."""
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    storage = tmp_path / "run-storage"
    storage.mkdir()
    run_dir = _write_run_manifest(
        tmp_path,
        _sample_manifest(
            workdir=tmp_path, storage=storage, pid=12345, run_id="run-001"
        ),
    )
    with WorkspaceLock(run_dir):
        result = runner.invoke(main, ["paths"])
    assert result.exit_code == 0, result.output
    assert str(storage) in result.output


def test_paths_live_manifest_wins_over_default(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live run with a custom ``storage_dir`` overrides the default.

    When the user ran ``start --storage-dir /custom`` the manifest
    records the override; ``paths`` must surface that path, not the
    workspace container.
    """
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)
    workdir = tmp_path / "project"
    workdir.mkdir()
    custom_storage = tmp_path / "custom-storage"
    custom_storage.mkdir()
    monkeypatch.chdir(workdir)
    run_dir = _write_run_manifest(
        workdir,
        _sample_manifest(
            workdir=workdir, storage=custom_storage, pid=12345, proxy_port=5050
        ),
    )

    with WorkspaceLock(run_dir):
        result = runner.invoke(main, ["paths", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert Path(payload["storage"]) == custom_storage


def test_paths_errors_on_multiple_live_runs_in_cwd(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare shell cannot pick among several live runs → actionable error."""
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)
    workdir = tmp_path / "project"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    dir1 = _write_run_manifest(
        workdir,
        _sample_manifest(workdir=workdir, storage=tmp_path / "s1", pid=1, run_id="r1"),
    )
    dir2 = _write_run_manifest(
        workdir,
        _sample_manifest(workdir=workdir, storage=tmp_path / "s2", pid=2, run_id="r2"),
    )

    with WorkspaceLock(dir1), WorkspaceLock(dir2):
        result = runner.invoke(main, ["paths"])
    assert result.exit_code == 2
    assert "2 live instances" in result.output
    assert "r1" in result.output
    assert "r2" in result.output


def test_paths_stale_manifest_ignored(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run manifest without a live lock must not hijack resolution."""
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)
    workdir = tmp_path / "project"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    _write_run_manifest(
        workdir,
        _sample_manifest(
            workdir=workdir,
            storage=tmp_path / "stale-storage",
            pid=1,
            proxy_port=5050,
        ),
    )
    # No lock held, so the manifest is stale and cannot identify storage.
    result = runner.invoke(main, ["paths", "--json"])
    assert result.exit_code == 2
    assert "no live Transport Matters instance" in result.output
    assert "stale-storage" not in result.output


def test_paths_respects_transport_matters_cwd_env_over_process_cwd(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``TRANSPORT_MATTERS_CWD`` overrides :meth:`Path.cwd` for the default selector.

    Simulates running ``transport-matters paths`` from inside a Claude session
    launched by ``transport-matters claude <project>`` after the user ``cd``'d
    into a subdirectory — resolution should still target the launching
    workspace, not the subdirectory.
    """
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)
    launch_dir = tmp_path / "project"
    launch_dir.mkdir()
    subdir = launch_dir / "api"
    subdir.mkdir()
    storage = tmp_path / "launch-storage"
    run_dir = _write_run_manifest(
        launch_dir,
        _sample_manifest(
            workdir=launch_dir, storage=storage, pid=1, run_id="run-launch"
        ),
    )
    monkeypatch.chdir(subdir)
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(launch_dir))

    with WorkspaceLock(run_dir):
        result = runner.invoke(main, ["paths", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert Path(payload["storage"]) == storage
    # Double-check: the subdir would have produced a different storage.
    assert Path(payload["storage"]) != workspace_root(subdir)


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
    storage = tmp_path / "storage-b"
    run_dir = _write_run_manifest(
        cwd_b,
        _sample_manifest(workdir=cwd_b, storage=storage, pid=1, run_id="run-b"),
    )
    monkeypatch.chdir(cwd_a)
    with WorkspaceLock(run_dir):
        result = runner.invoke(main, ["paths", "--workspace", str(cwd_b), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert Path(payload["storage"]) == storage


def test_paths_workspace_flag_resolves_a_runs_storage_dir(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--workspace <storage_dir>` resolves to that run — the exact value the
    same-CWD ambiguity error prints, so it round-trips. Must work for explicit
    `--storage-dir` runs whose storage lives OUTSIDE the workspaces tree.
    """
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)
    workdir = tmp_path / "project"
    workdir.mkdir()
    store_a = tmp_path / "explicit-a"
    store_a.mkdir()
    store_b = tmp_path / "explicit-b"
    store_b.mkdir()
    _write_run_manifest(
        workdir,
        _sample_manifest(workdir=workdir, storage=store_a, pid=1, run_id="r1"),
    )
    _write_run_manifest(
        workdir,
        _sample_manifest(workdir=workdir, storage=store_b, pid=2, run_id="r2"),
    )

    result = runner.invoke(main, ["paths", "--workspace", str(store_b), "--json"])
    assert result.exit_code == 0, result.output
    assert Path(json.loads(result.stdout)["storage"]) == store_b


def test_paths_workspace_flag_accepts_slug(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--workspace slug`` finds the matching run via manifest scan."""
    workdir = tmp_path / "projectX"
    workdir.mkdir()
    _write_run_manifest(
        workdir,
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
    slug = workspace_root(workdir).parent.name  # {slug} dir holds the {hash} subdir
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
