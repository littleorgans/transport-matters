import json
import stat
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from transport_matters import env_keys
from transport_matters.cli import main
from transport_matters.cli.home_seed import (
    _CLAUDE_DAEMON_LOCAL_NAMES,
    _assert_overlay_daemon_is_local,
    apply_claude_proxy_env_settings,
    claude_projects_root,
    codex_sessions_root,
    prepare_runtime_home_overlay,
    seed_home_dir,
)
from transport_matters.launch_environment import CLIENT_NAME_CLAUDE, CLIENT_NAME_CODEX

from ._helpers import _which_all, _which_by_name

runner = CliRunner()

if TYPE_CHECKING:
    from unittest.mock import MagicMock


class TestCodexSessionsRoot:
    def test_managed_home_dir_wins(self) -> None:
        # --agent-home-dir is the child's CODEX_HOME, so the launcher seeds under it.
        assert codex_sessions_root(Path("/managed/home"), {}) == Path("/managed/home/sessions")

    def test_falls_back_to_codex_home_env(self) -> None:
        root = codex_sessions_root(None, {"CODEX_HOME": "/custom/codex"})
        assert root == Path("/custom/codex/sessions")

    def test_falls_back_to_native_default(self) -> None:
        # No managed home and no CODEX_HOME → codex's native ~/.codex/sessions.
        assert codex_sessions_root(None, {}).parts[-2:] == (".codex", "sessions")


class TestClaudeProjectsRoot:
    def test_managed_home_dir_wins(self) -> None:
        # --agent-home-dir is the child's CLAUDE_CONFIG_DIR, so the launcher computes the owned path under it.
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


def test_claude_runtime_overlay_symlinks_state_and_keeps_control_files_local(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-claude"
    source.mkdir()
    (source / "skills").mkdir()
    (source / "skills" / "skill.md").write_text("skill\n", encoding="utf-8")
    (source / "projects").mkdir()
    (source / "daemon").mkdir()
    # Daemon dispatch state: queued jobs must never be shared with the source home.
    (source / "jobs").mkdir()
    (source / "jobs" / "job-1.json").write_text("{}\n", encoding="utf-8")
    # A source home that is (or contains) a git repo must not leak its .git into the overlay.
    (source / ".git").mkdir()
    (source / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    _write_json(source / ".claude.json", {"userID": "user-source"})
    source_settings = {"theme": "dark", "env": {"KEEP": "1"}}
    _write_json(source / "settings.json", source_settings)
    runtime = tmp_path / "runtime" / "claude"
    workdir = tmp_path / "project"
    workdir.mkdir()

    overlay = prepare_runtime_home_overlay(
        CLIENT_NAME_CLAUDE,
        source_home_dir=source,
        runtime_home_dir=runtime,
        working_dir=workdir,
        env={"CLAUDE_CONFIG_DIR": str(source)},
    )

    assert overlay.source_home_dir == source
    assert overlay.runtime_home_dir == runtime
    # User-visible state is symlinked for source fidelity.
    assert (runtime / "skills").is_symlink()
    assert (runtime / "skills").resolve() == (source / "skills").resolve()
    assert (runtime / "projects").is_symlink()
    assert (runtime / "projects").resolve() == (source / "projects").resolve()
    # Daemon control + dispatch state stays local (absent so Claude recreates it fresh),
    # never symlinked back to the source.
    assert not (runtime / "daemon").exists()
    assert not (runtime / "jobs").exists()
    assert not (runtime / "jobs").is_symlink()
    # .git is on the global never-symlink ignore list (no repo leak into the overlay).
    assert not (runtime / ".git").exists()
    assert not (runtime / ".git").is_symlink()
    assert not (runtime / "settings.json").is_symlink()
    assert not (runtime / ".claude.json").is_symlink()
    assert _read_json(source / "settings.json") == source_settings

    settings = _read_json(runtime / "settings.json")
    assert settings["theme"] == "dark"
    assert settings["env"] == {"KEEP": "1"}
    assert settings["skipDangerousModePermissionPrompt"] is True
    seeded = _read_json(runtime / ".claude.json")
    assert seeded["userID"] == "user-source"
    assert seeded["projects"][str(workdir)]["hasTrustDialogAccepted"] is True


def test_assert_overlay_daemon_is_local_rejects_daemon_state_symlinked_to_source(
    tmp_path: Path,
) -> None:
    # Every daemon control/dispatch name (daemon*, jobs) is route-sensitive; if any is a
    # symlink back to the source home the overlay is unsafe and launch must fail closed.
    assert "jobs" in _CLAUDE_DAEMON_LOCAL_NAMES
    source = tmp_path / "source-claude"
    source.mkdir()
    for name in _CLAUDE_DAEMON_LOCAL_NAMES:
        source_entry = source / name
        source_entry.mkdir()
        runtime = tmp_path / f"runtime-{name}"
        runtime.mkdir()
        (runtime / name).symlink_to(source_entry)
        with pytest.raises(ValueError, match="must not resolve to the source home"):
            _assert_overlay_daemon_is_local(source_home_dir=source, runtime_home_dir=runtime)


def test_assert_overlay_daemon_is_local_allows_fresh_local_daemon_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-claude"
    (source / "daemon").mkdir(parents=True)
    (source / "jobs").mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    # Real, local daemon + jobs dirs (not symlinks to the source) are allowed.
    (runtime / "daemon").mkdir()
    (runtime / "jobs").mkdir()
    _assert_overlay_daemon_is_local(source_home_dir=source, runtime_home_dir=runtime)


def test_claude_runtime_overlay_copies_native_default_account_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    source = tmp_path / ".claude"
    source.mkdir()
    _write_json(tmp_path / ".claude.json", {"userID": "native-user"})
    runtime = tmp_path / "runtime" / "claude"
    workdir = tmp_path / "project"
    workdir.mkdir()

    prepare_runtime_home_overlay(
        CLIENT_NAME_CLAUDE,
        source_home_dir=source,
        runtime_home_dir=runtime,
        working_dir=workdir,
        env={},
    )

    seeded = _read_json(runtime / ".claude.json")
    assert seeded["userID"] == "native-user"
    assert seeded["projects"][str(workdir)]["hasTrustDialogAccepted"] is True


def test_apply_claude_proxy_env_settings_updates_overlay_only(tmp_path: Path) -> None:
    source = tmp_path / "source-claude"
    source.mkdir()
    source_settings = {"theme": "dark", "env": {"KEEP": "1"}}
    _write_json(source / "settings.json", source_settings)
    runtime = tmp_path / "runtime" / "claude"
    runtime.mkdir(parents=True)
    _write_json(runtime / "settings.json", source_settings)

    apply_claude_proxy_env_settings(
        runtime_home_dir=runtime,
        proxy_url="http://127.0.0.1:54321",
        run_id="run-1",
    )
    # A bind-retry hands a new proxy port; the managed route must be rewritten.
    apply_claude_proxy_env_settings(
        runtime_home_dir=runtime,
        proxy_url="http://127.0.0.1:60001",
        run_id="run-1",
    )

    assert _read_json(source / "settings.json") == source_settings
    settings = _read_json(runtime / "settings.json")
    # Unrelated top-level settings and unrelated env keys are preserved.
    assert settings["theme"] == "dark"
    env = settings["env"]
    assert env["KEEP"] == "1"
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:60001"
    assert env[env_keys.RUN_ID] == "run-1"
    # TRANSPORT_MATTERS_AGENT_HOME_DIR is the overlay home, not the source (spec §1).
    assert env[env_keys.AGENT_HOME_DIR] == str(runtime)
    assert env["NO_PROXY"] == "127.0.0.1,localhost"
    assert _mode(runtime / "settings.json") == 0o600


def test_apply_claude_proxy_env_settings_writes_route_when_no_settings(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime" / "claude"
    runtime.mkdir(parents=True)

    apply_claude_proxy_env_settings(
        runtime_home_dir=runtime,
        proxy_url="http://127.0.0.1:54321",
        run_id="run-1",
    )

    env = _read_json(runtime / "settings.json")["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:54321"
    assert env[env_keys.AGENT_HOME_DIR] == str(runtime)
    assert _mode(runtime / "settings.json") == 0o600


def test_apply_claude_proxy_env_settings_rejects_non_object_env(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime" / "claude"
    runtime.mkdir(parents=True)
    _write_json(runtime / "settings.json", {"env": ["not", "an", "object"]})

    with pytest.raises(ValueError, match="env must contain a JSON object"):
        apply_claude_proxy_env_settings(
            runtime_home_dir=runtime,
            proxy_url="http://127.0.0.1:54321",
            run_id="run-1",
        )


def test_apply_claude_proxy_env_settings_rejects_non_object_root(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime" / "claude"
    runtime.mkdir(parents=True)
    (runtime / "settings.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        apply_claude_proxy_env_settings(
            runtime_home_dir=runtime,
            proxy_url="http://127.0.0.1:54321",
            run_id="run-1",
        )


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


def test_codex_runtime_overlay_copies_auth_config_and_symlinks_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-codex"
    source.mkdir()
    auth = source / "auth.json"
    auth.write_bytes(b'{"tokens":{"id":"source"}}\n')
    auth.chmod(0o600)
    (source / "config.toml").write_text('model = "gpt-5-codex"\n', encoding="utf-8")
    (source / "plugins").mkdir()
    (source / "plugins" / "plugin.json").write_text("{}\n", encoding="utf-8")
    runtime = tmp_path / "runtime" / "codex"
    workdir = tmp_path / "project"
    workdir.mkdir()

    prepare_runtime_home_overlay(
        CLIENT_NAME_CODEX,
        source_home_dir=source,
        runtime_home_dir=runtime,
        working_dir=workdir,
        env={"CODEX_HOME": str(source)},
    )

    assert not (runtime / "auth.json").is_symlink()
    assert not (runtime / "config.toml").is_symlink()
    assert (runtime / "auth.json").read_bytes() == auth.read_bytes()
    assert (runtime / "plugins").is_symlink()
    assert (runtime / "plugins").resolve() == (source / "plugins").resolve()
    source_config = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    runtime_config = tomllib.loads((runtime / "config.toml").read_text(encoding="utf-8"))
    assert source_config == {"model": "gpt-5-codex"}
    assert runtime_config["model"] == "gpt-5-codex"
    assert runtime_config["projects"][str(workdir)]["trust_level"] == "trusted"


def test_codex_overlay_repoints_hook_trust_state_to_overlay_home(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-codex"
    source.mkdir()
    (source / "hooks.json").write_text("{}\n", encoding="utf-8")
    # A home-relative hook key must follow the overlay; an absolute key outside the home stays.
    (source / "config.toml").write_text(
        'model = "gpt-5-codex"\n\n'
        f'[hooks.state."{source}/hooks.json:session_start:0:0"]\n'
        'trusted_hash = "sha256:home"\n\n'
        '[hooks.state."/opt/shared/hooks.json:stop:0:0"]\n'
        'trusted_hash = "sha256:shared"\n',
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime" / "codex"
    workdir = tmp_path / "project"
    workdir.mkdir()

    prepare_runtime_home_overlay(
        CLIENT_NAME_CODEX,
        source_home_dir=source,
        runtime_home_dir=runtime,
        working_dir=workdir,
        env={"CODEX_HOME": str(source)},
    )

    runtime_state = tomllib.loads((runtime / "config.toml").read_text(encoding="utf-8"))["hooks"][
        "state"
    ]
    # The hooks.json key now points at the overlay path where codex loads it, hash preserved.
    assert runtime_state[f"{runtime}/hooks.json:session_start:0:0"]["trusted_hash"] == "sha256:home"
    assert f"{source}/hooks.json:session_start:0:0" not in runtime_state
    # A key that did not live under the source home is left untouched.
    assert runtime_state["/opt/shared/hooks.json:stop:0:0"]["trusted_hash"] == "sha256:shared"
    # The operator's source config is never mutated.
    source_state = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))["hooks"][
        "state"
    ]
    assert f"{source}/hooks.json:session_start:0:0" in source_state


def test_claude_launch_runs_from_overlay_seeded_from_agent_home_dir(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    # --agent-home-dir is the operator's source home; populate it with account metadata.
    source = tmp_path / "homes" / "claude"
    source.mkdir(parents=True)
    source_config = {"userID": "user-source", "oauthAccount": {"accountUuid": "acct-source"}}
    _write_json(source / ".claude.json", source_config)
    monkeypatch.chdir(tmp_path)
    workdir = tmp_path / "project"
    workdir.mkdir()

    # The overlay is rmtree'd when the run finishes, so capture it during the spawn.
    captured: dict[str, Any] = {}

    def _capture_overlay(**kwargs: Any) -> None:
        overlay = Path(kwargs["client"].env["CLAUDE_CONFIG_DIR"])
        captured["overlay"] = overlay
        captured["claude_json"] = _read_json(overlay / ".claude.json")

    spy_run_client_children.side_effect = _capture_overlay

    result = runner.invoke(
        main,
        [
            "claude",
            "--work-dir",
            str(workdir),
            "--agent-home-dir",
            "homes/claude",
            "--no-system-prompt",
        ],
    )

    assert result.exit_code == 0, result.output
    spy_run_client_children.assert_called_once()
    overlay = captured["overlay"]
    # The child runs from the per-run overlay, seeded from the --agent-home-dir source.
    assert overlay.name == "claude"
    assert overlay.parent.name == "runtime-home"
    seeded = captured["claude_json"]
    assert seeded["userID"] == "user-source"
    assert seeded["projects"][str(workdir)]["hasTrustDialogAccepted"] is True
    # The operator's source home is not mutated by the run (cwd trust lands in the overlay).
    assert _read_json(source / ".claude.json") == source_config


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
            "--agent-home-dir",
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
