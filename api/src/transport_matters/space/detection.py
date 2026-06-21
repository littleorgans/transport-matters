from __future__ import annotations

import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from transport_matters.workspace import workspace_id

GIT_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class SpaceDetectionError(RuntimeError):
    code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class DetectedWorktree:
    path: Path
    workspace_slug: str
    workspace_hash: str
    branch_name: str | None
    head_oid: str | None
    is_primary: bool
    missing: bool = False


@dataclass(frozen=True)
class DetectedSpace:
    name: str
    primary_path: Path
    repo_instance_key: str | None
    git_common_dir: Path | None
    worktrees: tuple[DetectedWorktree, ...]


def repo_instance_key(git_common_dir: Path) -> str:
    resolved = git_common_dir.expanduser().resolve(strict=False)
    return sha256(resolved.as_posix().encode("utf-8")).hexdigest()


def detect_space(cwd: Path | str, *, timeout_s: float = GIT_TIMEOUT_S) -> DetectedSpace:
    target = Path(cwd).expanduser()
    if not target.exists():
        raise SpaceDetectionError(
            "missing_path",
            f"cwd does not exist: {target}",
            {"cwd": str(target)},
        )
    if not target.is_dir():
        raise SpaceDetectionError(
            "invalid_cwd",
            f"cwd is not a directory: {target}",
            {"cwd": str(target)},
        )

    resolved_target = target.resolve()
    probe = _run_git(
        resolved_target,
        (
            "rev-parse",
            "--is-inside-work-tree",
            "--show-toplevel",
            "--git-common-dir",
            "--git-dir",
        ),
        timeout_s=timeout_s,
        allow_failure=True,
    )
    if probe.returncode != 0:
        return _plain_space(resolved_target)

    lines = probe.stdout.splitlines()
    if len(lines) < 4 or lines[0].strip() != "true":
        return _plain_space(resolved_target)

    toplevel = _resolve_git_path(lines[1], base=resolved_target)
    common_dir = _resolve_git_path(lines[2], base=resolved_target)
    _resolve_git_path(lines[3], base=resolved_target)
    worktrees = _detect_git_worktrees(toplevel, common_dir=common_dir, timeout_s=timeout_s)
    primary_path = _primary_path_from_worktrees(worktrees) or toplevel
    return DetectedSpace(
        name=primary_path.name,
        primary_path=primary_path,
        repo_instance_key=repo_instance_key(common_dir),
        git_common_dir=common_dir,
        worktrees=worktrees
        or (
            _worktree_from_path(
                toplevel,
                primary_path=toplevel,
                branch_name=None,
                head_oid=None,
            ),
        ),
    )


def _plain_space(cwd: Path) -> DetectedSpace:
    workspace = workspace_id(cwd)
    return DetectedSpace(
        name=cwd.name,
        primary_path=cwd,
        repo_instance_key=None,
        git_common_dir=None,
        worktrees=(
            DetectedWorktree(
                path=cwd,
                workspace_slug=workspace.slug,
                workspace_hash=workspace.hash,
                branch_name=None,
                head_oid=None,
                is_primary=True,
            ),
        ),
    )


def _detect_git_worktrees(
    toplevel: Path,
    *,
    common_dir: Path,
    timeout_s: float,
) -> tuple[DetectedWorktree, ...]:
    result = _run_git(
        toplevel,
        ("worktree", "list", "--porcelain", "-z"),
        timeout_s=timeout_s,
        allow_failure=False,
    )
    records = _parse_porcelain_z(result.stdout)
    primary_path = _primary_worktree_path(records, common_dir=common_dir) or toplevel
    worktrees: list[DetectedWorktree] = []
    for record in records:
        raw_path = record.get("worktree")
        if raw_path is None:
            continue
        path = Path(raw_path).expanduser().resolve(strict=False)
        worktrees.append(
            _worktree_from_path(
                path,
                primary_path=primary_path,
                branch_name=_branch_from_record(record),
                head_oid=record.get("HEAD"),
                missing=not path.exists(),
            )
        )
    return tuple(worktrees)


def _worktree_from_path(
    path: Path,
    *,
    primary_path: Path,
    branch_name: str | None,
    head_oid: str | None,
    missing: bool = False,
) -> DetectedWorktree:
    workspace = workspace_id(path)
    return DetectedWorktree(
        path=path,
        workspace_slug=workspace.slug,
        workspace_hash=workspace.hash,
        branch_name=branch_name,
        head_oid=head_oid,
        is_primary=path == primary_path,
        missing=missing,
    )


def _run_git(
    cwd: Path,
    args: tuple[str, ...],
    *,
    timeout_s: float,
    allow_failure: bool,
) -> subprocess.CompletedProcess[str]:
    argv = ["git", *args]
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise SpaceDetectionError(
            "git_unavailable",
            "git executable is unavailable",
            {"cwd": str(cwd), "argv": argv},
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SpaceDetectionError(
            "git_timeout",
            "git probe timed out",
            {"cwd": str(cwd), "argv": argv, "timeout_s": timeout_s},
        ) from exc

    if result.returncode != 0 and not allow_failure:
        raise SpaceDetectionError(
            "git_probe_failed",
            result.stderr.strip() or "git probe failed",
            {"cwd": str(cwd), "argv": argv, "returncode": result.returncode},
        )
    return result


def _resolve_git_path(value: str, *, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=False)


def _parse_porcelain_z(output: str) -> tuple[dict[str, str], ...]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for item in output.split("\0"):
        if item == "":
            if current:
                records.append(current)
                current = {}
            continue
        key, separator, value = item.partition(" ")
        current[key] = value if separator else ""
    if current:
        records.append(current)
    return tuple(records)


def _primary_worktree_path(
    records: tuple[dict[str, str], ...],
    *,
    common_dir: Path,
) -> Path | None:
    for record in records:
        raw_path = record.get("worktree")
        if raw_path is None or "bare" in record:
            continue
        path = Path(raw_path).expanduser().resolve(strict=False)
        if (path / ".git").resolve(strict=False) == common_dir:
            return path
    for record in records:
        raw_path = record.get("worktree")
        if raw_path is not None and "bare" not in record:
            return Path(raw_path).expanduser().resolve(strict=False)
    return None


def _primary_path_from_worktrees(worktrees: tuple[DetectedWorktree, ...]) -> Path | None:
    for worktree in worktrees:
        if worktree.is_primary:
            return worktree.path
    return None


def _branch_from_record(record: dict[str, str]) -> str | None:
    raw = record.get("branch")
    if raw is None or raw == "":
        return None
    return raw.removeprefix("refs/heads/")
