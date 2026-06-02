from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.sh"
ROOT_JUSTFILE = REPO_ROOT / "justfile"


def _run(command: list[str], cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
        **kwargs,
    )


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def test_install_release_recipe_defaults_to_latest_and_supports_listing() -> None:
    justfile = ROOT_JUSTFILE.read_text()

    assert 'install-release version="latest":' in justfile
    assert 'git fetch --quiet --tags origin' in justfile
    assert '--sort=-v:refname' in justfile
    assert (
        'uv tool install --force --refresh-package transport-matters '
        '"transport-matters==$version"'
        in justfile
    )
    assert 'transport-matters --version' in justfile


def test_install_local_recipe_reinstalls_editable_checkout_without_version_file() -> None:
    justfile = ROOT_JUSTFILE.read_text()

    assert "install-local:" in justfile
    assert "rm -f api/src/transport_matters/_version.py" in justfile
    assert (
        'uv tool install --force --python "$(cat api/.python-version)" '
        "--refresh-package transport-matters --editable ./api"
        in justfile
    )
    assert "tool-install-editable: install-local" in justfile


def test_release_install_waits_installs_exact_version_and_verifies_cli(tmp_path: Path) -> None:
    remote = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "calls.log"

    _run(["git", "init", "--bare", str(remote)], tmp_path)
    _run(["git", "init", "-b", "main", str(repo)], tmp_path)
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "Release Test"], repo)
    (repo / "scripts").mkdir()
    shutil.copy(RELEASE_SCRIPT, repo / "scripts" / "release.sh")
    (repo / "README.md").write_text("release test\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "initial"], repo)
    _run(["git", "remote", "add", "origin", str(remote)], repo)
    _run(["git", "push", "-u", "origin", "main"], repo)

    bin_dir.mkdir()
    _write_executable(
        bin_dir / "gh",
        f"""#!/usr/bin/env bash
echo "gh $*" >> {calls}
if [ "$1 $2" = "run list" ]; then
  echo 12345
fi
""",
    )
    _write_executable(
        bin_dir / "just",
        f"""#!/usr/bin/env bash
echo "just $*" >> {calls}
""",
    )
    _write_executable(
        bin_dir / "python3",
        f"""#!/usr/bin/env bash
echo "python3 $*" >> {calls}
exit 0
""",
    )
    _write_executable(
        bin_dir / "transport-matters",
        f"""#!/usr/bin/env bash
echo "transport-matters $*" >> {calls}
echo "transport-matters 9.8.7"
""",
    )

    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    result = _run(
        ["bash", "scripts/release.sh", "--yes", "--install", "9.8.7"],
        repo,
        env=env,
    )

    call_log = calls.read_text()
    assert "[push] pushed v9.8.7 to origin" in result.stdout
    assert "Waiting for release workflow run for v9.8.7" in result.stdout
    assert "Installing released CLI with: just install-release 9.8.7" in result.stdout
    assert "gh run list" in call_log
    assert "gh run watch 12345 --exit-status" in call_log
    assert "python3 - 9.8.7" in call_log
    assert "just install-release 9.8.7" in call_log
    assert "transport-matters --version" in call_log


def test_release_install_is_not_valid_with_dry_run() -> None:
    result = subprocess.run(
        ["bash", str(RELEASE_SCRIPT), "--dry-run", "--install", "9.8.7"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "--install cannot be combined with --dry-run" in result.stderr
