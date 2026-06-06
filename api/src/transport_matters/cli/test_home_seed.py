import json
import stat
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from transport_matters.cli import main
from transport_matters.cli.home_seed import (
    claude_projects_root,
    codex_sessions_root,
    seed_home_dir,
)
from transport_matters.cli.launch_runtime import CLIENT_NAME_CLAUDE, CLIENT_NAME_CODEX

from ._helpers import _which_all, _which_by_name

runner = CliRunner()

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    import pytest


class TestCodexSessionsRoot:
    def test_managed_home_dir_wins(self) -> None:
        # --home-dir is the child's CODEX_HOME, so the launcher seeds under it.
        assert codex_sessions_root(Path("/managed/home"), {}) == Path("/managed/home/sessions")

    def test_falls_back_to_codex_home_env(self) -> None:
        root = codex_sessions_root(None, {"CODEX_HOME": "/custom/codex"})
        assert root == Path("/custom/codex/sessions")

    def test_falls_back_to_native_default(self) -> None:
        # No managed home and no CODEX_HOME → codex's native ~/.codex/sessions.
        assert codex_sessions_root(None, {}).parts[-2:] == (".codex", "sessions")


class TestClaudeProjectsRoot:
    def test_managed_home_dir_wins(self) -> None:
        # --home-dir is the child's CLAUDE_CONFIG_DIR, so the launcher computes the owned path under it.
        assert claude_projects_root(Path("/managed/home"), {}) == Path("/managed/home/projects")

    def test_falls_back_to_claude_config_dir_env(self) -> None:
        root = claude_projects_root(None, {"CLAUDE_CONFIG_DIR": "/custom/claude"})
        assert root == Path("/custom/claude/projects")

    def test_falls_back_to_native_default(self) -> None:
        # No managed home and no CLAUDE_CONFIG_DIR → claude's native ~/.claude/projects.
        assert claude_projects_root(None, {}).parts[-2:] == (".claude", "projects")


def test_claude_seed_fresh_home_copies_metadata_and_trust(
    tmp_path: Path,
) -> None:
    source = tmp_path / "default-claude"
    source.mkdir()
    _write_json(
        source / ".claude.json",
        {
            "userID": "user-default",
            "oauthAccount": {
                "accountUuid": "acct-default",
                "emailAddress": "default@example.test",
            },
            "projects": {"/other": {"hasTrustDialogAccepted": True}},
        },
    )
    home = tmp_path / "managed-claude"
    workdir = tmp_path / "project"
    workdir.mkdir()

    seed_home_dir(
        CLIENT_NAME_CLAUDE,
        home_dir=home,
        working_dir=workdir,
        env={"CLAUDE_CONFIG_DIR": str(source)},
    )

    seeded = _read_json(home / ".claude.json")
    assert seeded["hasCompletedOnboarding"] is True
    assert seeded["userID"] == "user-default"
    assert seeded["oauthAccount"] == {
        "accountUuid": "acct-default",
        "emailAddress": "default@example.test",
    }
    assert seeded["projects"][str(workdir)]["hasTrustDialogAccepted"] is True
    assert _mode(home / ".claude.json") == 0o600


def test_claude_seed_preserves_existing_account(tmp_path: Path) -> None:
    source = tmp_path / "default-claude"
    source.mkdir()
    _write_json(
        source / ".claude.json",
        {
            "userID": "user-default",
            "oauthAccount": {"accountUuid": "acct-default"},
        },
    )
    home = tmp_path / "managed-claude"
    home.mkdir()
    _write_json(
        home / ".claude.json",
        {
            "userID": "user-existing",
            "oauthAccount": {"accountUuid": "acct-existing"},
            "projects": {"/other": {"mode": "keep"}},
        },
    )
    workdir = tmp_path / "project"
    workdir.mkdir()

    seed_home_dir(
        CLIENT_NAME_CLAUDE,
        home_dir=home,
        working_dir=workdir,
        env={"CLAUDE_CONFIG_DIR": str(source)},
    )

    seeded = _read_json(home / ".claude.json")
    assert seeded["userID"] == "user-existing"
    assert seeded["oauthAccount"] == {"accountUuid": "acct-existing"}
    assert seeded["projects"]["/other"] == {"mode": "keep"}
    assert seeded["projects"][str(workdir)]["hasTrustDialogAccepted"] is True
    assert seeded["hasCompletedOnboarding"] is True


def test_claude_seed_writes_skip_dangerous_mode_setting(tmp_path: Path) -> None:
    source = tmp_path / "default-claude"
    source.mkdir()
    _write_json(source / ".claude.json", {"userID": "user-default"})
    home = tmp_path / "managed-claude"
    workdir = tmp_path / "project"
    workdir.mkdir()

    seed_home_dir(
        CLIENT_NAME_CLAUDE,
        home_dir=home,
        working_dir=workdir,
        env={"CLAUDE_CONFIG_DIR": str(source)},
    )

    settings = _read_json(home / "settings.json")
    assert settings["skipDangerousModePermissionPrompt"] is True


def test_claude_seed_preserves_existing_settings(tmp_path: Path) -> None:
    source = tmp_path / "default-claude"
    source.mkdir()
    _write_json(source / ".claude.json", {"userID": "user-default"})
    home = tmp_path / "managed-claude"
    home.mkdir()
    _write_json(home / "settings.json", {"theme": "dark"})
    workdir = tmp_path / "project"
    workdir.mkdir()

    seed_home_dir(
        CLIENT_NAME_CLAUDE,
        home_dir=home,
        working_dir=workdir,
        env={"CLAUDE_CONFIG_DIR": str(source)},
    )

    settings = _read_json(home / "settings.json")
    assert settings["theme"] == "dark"
    assert settings["skipDangerousModePermissionPrompt"] is True


def test_codex_seed_fresh_home_copies_auth_0600_and_trust(
    tmp_path: Path,
) -> None:
    source = tmp_path / "default-codex"
    source.mkdir()
    auth = source / "auth.json"
    auth.write_bytes(b'{"tokens":{"id":"source"}}\n')
    auth.chmod(0o600)
    home = tmp_path / "managed-codex"
    workdir = tmp_path / "project"
    workdir.mkdir()

    seed_home_dir(
        CLIENT_NAME_CODEX,
        home_dir=home,
        working_dir=workdir,
        env={"CODEX_HOME": str(source)},
    )

    assert (home / "auth.json").read_bytes() == auth.read_bytes()
    assert _mode(home / "auth.json") == 0o600
    config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert config["projects"][str(workdir)]["trust_level"] == "trusted"
    assert _mode(home / "config.toml") == 0o600


def test_codex_seed_same_cwd_twice_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "default-codex"
    source.mkdir()
    (source / "auth.json").write_bytes(b'{"tokens":{"id":"source"}}\n')
    home = tmp_path / "managed-codex"
    workdir = tmp_path / "project"
    workdir.mkdir()

    for _ in range(2):
        seed_home_dir(
            CLIENT_NAME_CODEX,
            home_dir=home,
            working_dir=workdir,
            env={"CODEX_HOME": str(source)},
        )

    config_text = (home / "config.toml").read_text(encoding="utf-8")
    config = tomllib.loads(config_text)
    assert config["projects"][str(workdir)]["trust_level"] == "trusted"
    assert config_text.count('trust_level = "trusted"') == 1


def test_codex_seed_merges_two_cwds(tmp_path: Path) -> None:
    source = tmp_path / "default-codex"
    source.mkdir()
    (source / "auth.json").write_bytes(b'{"tokens":{"id":"source"}}\n')
    home = tmp_path / "managed-codex"
    workdirs = [tmp_path / "one", tmp_path / "two"]
    for workdir in workdirs:
        workdir.mkdir()
        seed_home_dir(
            CLIENT_NAME_CODEX,
            home_dir=home,
            working_dir=workdir,
            env={"CODEX_HOME": str(source)},
        )

    config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    for workdir in workdirs:
        assert config["projects"][str(workdir)]["trust_level"] == "trusted"


def test_codex_seed_preserves_existing_auth_and_project_sibling_keys(
    tmp_path: Path,
) -> None:
    source = tmp_path / "default-codex"
    source.mkdir()
    (source / "auth.json").write_bytes(b'{"tokens":{"id":"source"}}\n')
    home = tmp_path / "managed-codex"
    home.mkdir()
    existing_auth = home / "auth.json"
    existing_auth.write_bytes(b'{"tokens":{"id":"existing"}}\n')
    existing_auth.chmod(0o600)
    workdir = tmp_path / "project"
    workdir.mkdir()
    (home / "config.toml").write_text(
        f'model = "gpt-5-codex"\n\n[projects."{workdir}"]\nnotes = "keep"\n',
        encoding="utf-8",
    )

    for _ in range(2):
        seed_home_dir(
            CLIENT_NAME_CODEX,
            home_dir=home,
            working_dir=workdir,
            env={"CODEX_HOME": str(source)},
        )

    assert existing_auth.read_bytes() == b'{"tokens":{"id":"existing"}}\n'
    config_text = (home / "config.toml").read_text(encoding="utf-8")
    config = tomllib.loads(config_text)
    assert config["projects"][str(workdir)]["notes"] == "keep"
    assert config["projects"][str(workdir)]["trust_level"] == "trusted"
    assert config_text.count('trust_level = "trusted"') == 1


def test_claude_launch_seeds_home_dir(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    source = tmp_path / "default-claude"
    source.mkdir()
    _write_json(
        source / ".claude.json",
        {
            "userID": "user-default",
            "oauthAccount": {"accountUuid": "acct-default"},
        },
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(source))
    monkeypatch.chdir(tmp_path)
    workdir = tmp_path / "project"
    workdir.mkdir()

    result = runner.invoke(
        main,
        [
            "claude",
            "--work-dir",
            str(workdir),
            "--home-dir",
            "homes/claude",
            "--no-system-prompt",
        ],
    )

    assert result.exit_code == 0, result.output
    spy_run_client_children.assert_called_once()
    seeded = _read_json(tmp_path / "homes" / "claude" / ".claude.json")
    assert seeded["userID"] == "user-default"
    assert seeded["projects"][str(workdir)]["hasTrustDialogAccepted"] is True


def test_codex_launch_seeds_home_dir(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    source = tmp_path / "default-codex"
    source.mkdir()
    (source / "auth.json").write_bytes(b'{"tokens":{"id":"source"}}\n')
    monkeypatch.setenv("CODEX_HOME", str(source))
    bundle_path = tmp_path / "ca.pem"
    bundle_path.write_text("bundle", encoding="utf-8")
    monkeypatch.setattr(
        "transport_matters.cli.resolve_codex_ca_certificate",
        lambda *, env, bundle_dir: bundle_path,
    )
    monkeypatch.chdir(tmp_path)
    workdir = tmp_path / "project"
    workdir.mkdir()

    result = runner.invoke(
        main,
        [
            "codex",
            "--work-dir",
            str(workdir),
            "--home-dir",
            "homes/codex",
            "--proxy-port",
            "9000",
            "--web-port",
            "9001",
        ],
    )

    assert result.exit_code == 0, result.output
    spy_run_client_children.assert_called_once()
    home = tmp_path / "homes" / "codex"
    assert (home / "auth.json").read_bytes() == b'{"tokens":{"id":"source"}}\n'
    config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert config["projects"][str(workdir)]["trust_level"] == "trusted"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)
