from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from transport_matters.space.detection import SpaceDetectionError, detect_space, repo_instance_key
from transport_matters.workspace import workspace_id


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    (path / "README.md").write_text("root\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")
    return path


def test_plain_directory_detects_single_primary_degenerate_worktree(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    detected = detect_space(plain)
    expected_workspace = workspace_id(plain)

    assert detected.name == "plain"
    assert detected.primary_path == plain.resolve()
    assert detected.repo_instance_key is None
    assert detected.git_common_dir is None
    assert len(detected.worktrees) == 1
    worktree = detected.worktrees[0]
    assert worktree.path == plain.resolve()
    assert worktree.workspace_slug == expected_workspace.slug
    assert worktree.workspace_hash == expected_workspace.hash
    assert worktree.branch_name is None
    assert worktree.head_oid is None
    assert worktree.is_primary is True
    assert worktree.missing is False


def test_git_repository_detects_all_worktrees_with_branch_head_and_primary(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-b", "feature", str(linked), "HEAD")

    detected = detect_space(repo)
    common_dir = (repo / ".git").resolve()

    assert detected.repo_instance_key == repo_instance_key(common_dir)
    assert detected.git_common_dir == common_dir
    paths = {item.path for item in detected.worktrees}
    assert paths == {repo.resolve(), linked.resolve()}
    by_path = {item.path: item for item in detected.worktrees}
    assert by_path[repo.resolve()].branch_name == "main"
    assert by_path[linked.resolve()].branch_name == "feature"
    assert by_path[repo.resolve()].head_oid == by_path[linked.resolve()].head_oid
    assert by_path[repo.resolve()].is_primary is True
    assert by_path[linked.resolve()].is_primary is False


def test_relative_git_common_dir_is_resolved_against_target_cwd_not_process_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    detected = detect_space(repo)

    assert Path.cwd() == other
    assert detected.git_common_dir == (repo / ".git").resolve()
    assert detected.repo_instance_key == repo_instance_key(repo / ".git")
    assert detected.worktrees[0].is_primary is True


def test_missing_git_worktree_path_is_flagged(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-b", "feature", str(linked), "HEAD")
    shutil.rmtree(linked)

    detected = detect_space(repo)

    by_path = {item.path: item for item in detected.worktrees}
    assert by_path[linked.resolve()].missing is True
    assert by_path[repo.resolve()].missing is False


def test_not_a_worktree_detects_as_plain_degenerate_space(tmp_path: Path) -> None:
    bare = tmp_path / "bare.git"
    _git(tmp_path, "init", "--bare", str(bare))

    detected = detect_space(bare)

    assert detected.name == "bare.git"
    assert detected.repo_instance_key is None
    assert detected.git_common_dir is None
    assert len(detected.worktrees) == 1
    assert detected.worktrees[0].path == bare.resolve()
    assert detected.worktrees[0].is_primary is True


def test_missing_path_is_a_structured_detection_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(SpaceDetectionError) as exc_info:
        detect_space(missing)

    assert exc_info.value.code == "missing_path"
    assert exc_info.value.details == {"cwd": str(missing)}


def test_git_unavailable_is_a_structured_detection_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    def raise_missing(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", raise_missing)

    with pytest.raises(SpaceDetectionError) as exc_info:
        detect_space(plain)

    assert exc_info.value.code == "git_unavailable"


def test_git_timeout_is_a_structured_detection_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    def raise_timeout(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["git"], timeout=0.01)

    monkeypatch.setattr(subprocess, "run", raise_timeout)

    with pytest.raises(SpaceDetectionError) as exc_info:
        detect_space(plain, timeout_s=0.01)

    assert exc_info.value.code == "git_timeout"
