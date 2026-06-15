from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from click.exceptions import Exit

from transport_matters import env_keys
from transport_matters.cli.home_seed import apply_claude_proxy_env_settings
from transport_matters.cli.launch_profile import (
    ClaudeLaunchProfile,
    CodexLaunchProfile,
    prepare_managed_session,
)
from transport_matters.cli.runtime_home import (
    RuntimeHomeMode,
    RuntimeTemplateRef,
    plan_runtime_home,
    prepare_runtime_home,
)
from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
    decode_source_descriptor,
    encode_source_descriptor,
)
from transport_matters.launch_environment import (
    CLIENT_NAME_CLAUDE,
    CLIENT_NAME_CODEX,
    build_launch_env,
)


def _now() -> datetime:
    return datetime(2026, 6, 15, 12, 0, 0)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _tree_fingerprint(root: Path) -> tuple[tuple[str, str, bytes | str | None], ...]:
    entries: list[tuple[str, str, bytes | str | None]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((rel, "symlink", str(path.readlink())))
        elif path.is_dir():
            entries.append((rel, "dir", None))
        else:
            entries.append((rel, "file", path.read_bytes()))
    return tuple(entries)


def test_codex_template_overlay_links_native_auth_fallback(tmp_path: Path) -> None:
    native = tmp_path / "native-codex"
    native.mkdir()
    (native / "auth.json").write_bytes(b'{"tokens":{"id":"native"}}\n')
    template = tmp_path / "templates" / "codex"
    template.mkdir(parents=True)
    (template / "config.toml").write_text('model = "gpt-5-codex"\n', encoding="utf-8")
    runtime_root = tmp_path / "run" / "runtime-home"
    workdir = tmp_path / "project"
    workdir.mkdir()

    plan = plan_runtime_home(
        CLIENT_NAME_CODEX,
        home_dir=None,
        runtime_template=RuntimeTemplateRef(
            template_id="codex/base",
            client_name=CLIENT_NAME_CODEX,
            template_home=template,
            provenance={"source": "test"},
        ),
        runtime_home_root=runtime_root,
        client_path="/bin/codex",
        env={"CODEX_HOME": str(native)},
        use_runtime_overlay=True,
    )
    prepare_runtime_home(plan, working_dir=workdir, env={"CODEX_HOME": str(native)})

    assert plan.mode == RuntimeHomeMode.TEMPLATE
    assert plan.content_source == template
    assert plan.auth_source == native
    assert plan.child_home == runtime_root / CLIENT_NAME_CODEX
    auth_link = plan.child_home / "auth.json"
    assert auth_link.is_symlink()
    assert auth_link.resolve() == (native / "auth.json").resolve()
    assert auth_link.read_bytes() == b'{"tokens":{"id":"native"}}\n'


def test_template_overlay_symlinks_unknown_entries(tmp_path: Path) -> None:
    native = tmp_path / "native-codex"
    native.mkdir()
    (native / "auth.json").write_text("{}\n", encoding="utf-8")
    template = tmp_path / "templates" / "codex"
    template.mkdir(parents=True)
    (template / "config.toml").write_text('model = "gpt-5-codex"\n', encoding="utf-8")
    (template / "custom-file.txt").write_text("hello\n", encoding="utf-8")
    custom_dir = template / "custom-dir"
    custom_dir.mkdir()
    (custom_dir / "nested.txt").write_text("nested\n", encoding="utf-8")

    plan = plan_runtime_home(
        CLIENT_NAME_CODEX,
        home_dir=None,
        runtime_template=RuntimeTemplateRef(
            template_id="codex/base",
            client_name=CLIENT_NAME_CODEX,
            template_home=template,
            provenance={},
        ),
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path="/bin/codex",
        env={"CODEX_HOME": str(native)},
        use_runtime_overlay=True,
    )
    prepare_runtime_home(plan, working_dir=tmp_path, env={"CODEX_HOME": str(native)})

    assert plan.child_home is not None
    file_link = plan.child_home / "custom-file.txt"
    dir_link = plan.child_home / "custom-dir"
    assert file_link.is_symlink()
    assert file_link.resolve() == (template / "custom-file.txt").resolve()
    assert file_link.read_text(encoding="utf-8") == "hello\n"
    assert dir_link.is_symlink()
    assert dir_link.resolve() == custom_dir.resolve()
    assert (dir_link / "nested.txt").read_text(encoding="utf-8") == "nested\n"


def test_template_overlay_excludes_runtime_toml(tmp_path: Path) -> None:
    native = tmp_path / "native-codex"
    native.mkdir()
    (native / "auth.json").write_text("{}\n", encoding="utf-8")
    template = tmp_path / "templates" / "codex"
    template.mkdir(parents=True)
    (template / "config.toml").write_text('model = "gpt-5-codex"\n', encoding="utf-8")
    (template / "runtime.toml").write_text("[runtime]\n", encoding="utf-8")

    plan = plan_runtime_home(
        CLIENT_NAME_CODEX,
        home_dir=None,
        runtime_template=RuntimeTemplateRef(
            template_id="codex/base",
            client_name=CLIENT_NAME_CODEX,
            template_home=template,
            provenance={},
        ),
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path="/bin/codex",
        env={"CODEX_HOME": str(native)},
        use_runtime_overlay=True,
    )
    prepare_runtime_home(plan, working_dir=tmp_path, env={"CODEX_HOME": str(native)})

    assert plan.child_home is not None
    assert not (plan.child_home / "runtime.toml").exists()
    assert not (plan.child_home / "runtime.toml").is_symlink()


@pytest.mark.parametrize(
    ("home_dir", "runtime_template"),
    [
        (None, None),
        (Path("manual-codex"), None),
    ],
)
def test_non_template_overlays_keep_implicit_catch_all_symlinks(
    tmp_path: Path,
    home_dir: Path | None,
    runtime_template: RuntimeTemplateRef | None,
) -> None:
    source = tmp_path / (str(home_dir) if home_dir is not None else "native-codex")
    source.mkdir()
    (source / "auth.json").write_text("{}\n", encoding="utf-8")
    (source / "config.toml").write_text('model = "gpt-5-codex"\n', encoding="utf-8")
    (source / "operator-content").mkdir()

    plan = plan_runtime_home(
        CLIENT_NAME_CODEX,
        home_dir=source if home_dir is not None else None,
        runtime_template=runtime_template,
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path="/bin/codex",
        env={"CODEX_HOME": str(source)},
        use_runtime_overlay=True,
    )
    prepare_runtime_home(plan, working_dir=tmp_path, env={"CODEX_HOME": str(source)})

    assert plan.mode in {RuntimeHomeMode.NATIVE, RuntimeHomeMode.MANUAL}
    assert plan.child_home is not None
    content_link = plan.child_home / "operator-content"
    assert content_link.is_symlink()
    assert content_link.resolve() == (source / "operator-content").resolve()


def test_codex_template_descriptor_seeds_runtime_sessions_without_mutating_template(
    tmp_path: Path,
) -> None:
    native = tmp_path / "native-codex"
    native.mkdir()
    (native / "auth.json").write_text("{}\n", encoding="utf-8")
    template = tmp_path / "templates" / "codex"
    template.mkdir(parents=True)
    (template / "config.toml").write_text('model = "gpt-5-codex"\n', encoding="utf-8")
    workdir = tmp_path / "project"
    workdir.mkdir()

    plan = plan_runtime_home(
        CLIENT_NAME_CODEX,
        home_dir=None,
        runtime_template=RuntimeTemplateRef(
            template_id="codex/base",
            client_name=CLIENT_NAME_CODEX,
            template_home=template,
            provenance={},
        ),
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path="/bin/codex",
        env={"CODEX_HOME": str(native)},
        use_runtime_overlay=True,
    )
    prepare_runtime_home(plan, working_dir=workdir, env={"CODEX_HOME": str(native)})

    assert plan.descriptor_home == plan.child_home
    managed = prepare_managed_session(
        CodexLaunchProfile(),
        client_path="/bin/codex",
        passthrough=[],
        working_dir=workdir,
        home_dir=plan.descriptor_home,
        env={"CODEX_HOME": str(native)},
        now=_now(),
        write=True,
    )

    assert managed is not None
    child_home = plan.child_home
    assert child_home is not None
    source = decode_source_descriptor(managed.source_descriptor)
    assert isinstance(source, FileTailSource)
    assert Path(source.path).is_relative_to(child_home / "sessions")
    assert source.home_dir == str(child_home)
    assert (child_home / "sessions").is_dir()
    assert not (template / "sessions").exists()


def test_codex_template_tree_is_byte_identical_after_full_launch_prep(
    tmp_path: Path,
) -> None:
    native = tmp_path / "native-codex"
    native.mkdir()
    (native / "auth.json").write_text("{}\n", encoding="utf-8")
    template = tmp_path / "templates" / "codex"
    template.mkdir(parents=True)
    (template / "config.toml").write_text(
        f'model = "gpt-5-codex"\n[hooks.state."{template}/hooks.json:stop:0:0"]\n'
        'trusted_hash = "sha256:template"\n',
        encoding="utf-8",
    )
    (template / "hooks.json").write_text("{}\n", encoding="utf-8")
    (template / "plugins").mkdir()
    (template / "plugins" / "plugin.json").write_text("{}\n", encoding="utf-8")
    (template / "sessions").mkdir()
    before = _tree_fingerprint(template)
    workdir = tmp_path / "project"
    workdir.mkdir()

    plan = plan_runtime_home(
        CLIENT_NAME_CODEX,
        home_dir=None,
        runtime_template=RuntimeTemplateRef(
            template_id="codex/base",
            client_name=CLIENT_NAME_CODEX,
            template_home=template,
            provenance={},
        ),
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path="/bin/codex",
        env={"CODEX_HOME": str(native)},
        use_runtime_overlay=True,
    )
    prepare_runtime_home(plan, working_dir=workdir, env={"CODEX_HOME": str(native)})
    managed = prepare_managed_session(
        CodexLaunchProfile(),
        client_path="/bin/codex",
        passthrough=[],
        working_dir=workdir,
        home_dir=plan.descriptor_home,
        env={"CODEX_HOME": str(native)},
        now=_now(),
        write=True,
    )

    assert managed is not None
    assert _tree_fingerprint(template) == before
    assert plan.child_home is not None
    assert not (plan.child_home / "sessions").is_symlink()
    assert (plan.child_home / "sessions").is_dir()
    assert (plan.child_home / "plugins").is_symlink()
    assert (plan.child_home / "hooks.json").is_symlink()


def test_claude_template_descriptor_resolves_under_runtime_projects(tmp_path: Path) -> None:
    native = tmp_path / "native-claude"
    native.mkdir()
    _write_json(native / ".claude.json", {"userID": "native-user"})
    template = tmp_path / "templates" / "claude"
    template.mkdir(parents=True)
    _write_json(template / ".claude.json", {})
    workdir = tmp_path / "project"
    workdir.mkdir()

    plan = plan_runtime_home(
        CLIENT_NAME_CLAUDE,
        home_dir=None,
        runtime_template=RuntimeTemplateRef(
            template_id="claude/base",
            client_name=CLIENT_NAME_CLAUDE,
            template_home=template,
            provenance={},
        ),
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path="/bin/claude",
        env={"CLAUDE_CONFIG_DIR": str(native)},
        use_runtime_overlay=True,
    )
    prepare_runtime_home(plan, working_dir=workdir, env={"CLAUDE_CONFIG_DIR": str(native)})

    assert plan.descriptor_home == plan.child_home
    managed = prepare_managed_session(
        ClaudeLaunchProfile(),
        client_path="/bin/claude",
        passthrough=[],
        working_dir=workdir,
        home_dir=plan.descriptor_home,
        env={"CLAUDE_CONFIG_DIR": str(native)},
        now=_now(),
        write=True,
    )

    assert managed is not None
    child_home = plan.child_home
    assert child_home is not None
    source = decode_source_descriptor(managed.source_descriptor)
    assert isinstance(source, FileTailSource)
    assert Path(source.path).is_relative_to(child_home / "projects")
    assert source.home_dir == str(child_home)
    assert not (child_home / "projects").is_symlink()
    assert not (template / "projects").exists()


def test_claude_template_tree_is_byte_identical_after_full_launch_prep(
    tmp_path: Path,
) -> None:
    native = tmp_path / "native-claude"
    native.mkdir()
    _write_json(native / ".claude.json", {"userID": "native-user"})
    (native / ".credentials.json").write_text("{}\n", encoding="utf-8")
    template = tmp_path / "templates" / "claude"
    template.mkdir(parents=True)
    _write_json(template / ".claude.json", {})
    _write_json(template / "settings.json", {"env": {"KEEP": "1"}})
    (template / "skills").mkdir()
    (template / "skills" / "SKILL.md").write_text("skill\n", encoding="utf-8")
    (template / "projects").mkdir()
    before = _tree_fingerprint(template)
    workdir = tmp_path / "project"
    workdir.mkdir()

    plan = plan_runtime_home(
        CLIENT_NAME_CLAUDE,
        home_dir=None,
        runtime_template=RuntimeTemplateRef(
            template_id="claude/base",
            client_name=CLIENT_NAME_CLAUDE,
            template_home=template,
            provenance={},
        ),
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path="/bin/claude",
        env={"CLAUDE_CONFIG_DIR": str(native)},
        use_runtime_overlay=True,
    )
    prepare_runtime_home(plan, working_dir=workdir, env={"CLAUDE_CONFIG_DIR": str(native)})
    managed = prepare_managed_session(
        ClaudeLaunchProfile(),
        client_path="/bin/claude",
        passthrough=[],
        working_dir=workdir,
        home_dir=plan.descriptor_home,
        env={"CLAUDE_CONFIG_DIR": str(native)},
        now=_now(),
        write=True,
    )
    assert managed is not None
    assert plan.child_home is not None
    apply_claude_proxy_env_settings(
        runtime_home_dir=plan.child_home,
        proxy_url="http://127.0.0.1:8787",
        run_id="run-1",
    )

    assert _tree_fingerprint(template) == before
    assert not (plan.child_home / "projects").is_symlink()
    assert (plan.child_home / "projects").is_dir()
    assert (plan.child_home / "skills").is_symlink()


def test_manual_plan_preserves_descriptor_home_and_no_overlay(tmp_path: Path) -> None:
    manual = tmp_path / "manual-codex"
    manual.mkdir()
    invalid_template = tmp_path / "invalid-template"
    invalid_template.mkdir()
    (invalid_template / "auth.json").write_text("{}", encoding="utf-8")
    plan = plan_runtime_home(
        CLIENT_NAME_CODEX,
        home_dir=manual,
        runtime_template=RuntimeTemplateRef(
            template_id="codex/base",
            client_name=CLIENT_NAME_CODEX,
            template_home=invalid_template,
            provenance={},
        ),
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path="/bin/codex",
        env={},
        use_runtime_overlay=False,
    )

    assert plan.mode == RuntimeHomeMode.MANUAL
    assert plan.child_home == manual
    assert plan.descriptor_home == manual
    assert prepare_runtime_home(plan, working_dir=tmp_path, env={}) is None


def test_manual_plan_ignores_invalid_runtime_template(tmp_path: Path) -> None:
    manual = tmp_path / "manual-codex"
    manual.mkdir()
    missing_template = tmp_path / "missing-template"

    plan = plan_runtime_home(
        CLIENT_NAME_CODEX,
        home_dir=manual,
        runtime_template=RuntimeTemplateRef(
            template_id="codex/base",
            client_name=CLIENT_NAME_CODEX,
            template_home=missing_template,
            provenance={},
        ),
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path="/bin/codex",
        env={},
        use_runtime_overlay=False,
    )

    assert plan.mode == RuntimeHomeMode.MANUAL
    assert plan.content_source == manual
    assert plan.child_home == manual


def test_proxy_only_plan_preserves_manual_home(tmp_path: Path) -> None:
    manual = tmp_path / "manual-codex"
    manual.mkdir()

    plan = plan_runtime_home(
        CLIENT_NAME_CODEX,
        home_dir=manual,
        runtime_template=None,
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path=None,
        env={},
        use_runtime_overlay=False,
    )

    assert plan.mode == RuntimeHomeMode.PROXY_ONLY
    assert plan.content_source == manual
    assert plan.auth_source == manual
    assert plan.child_home == manual
    assert plan.descriptor_home == manual
    assert prepare_runtime_home(plan, working_dir=tmp_path, env={}) is None


def test_build_launch_env_drops_stale_launch_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(env_keys.LAUNCH_FIELDS, '{"runtime_template":{"template_id":"stale"}}')

    env = build_launch_env(
        working_dir=tmp_path / "workspace",
        storage_dir=tmp_path / "storage",
        proxy_port=8787,
        web_port=8788,
        run_id="run-1",
        launch_fields={},
    )

    assert env_keys.LAUNCH_FIELDS not in env


def test_run_codex_force_http_fallback_still_resolves_addons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from transport_matters.cli import codex_cmd

    addon = tmp_path / "addon.py"
    addon.write_text("# addon\n", encoding="utf-8")
    fallback = tmp_path / "fallback.py"
    fallback.write_text("# fallback\n", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_resolve_codex_addons_and_ca(**kwargs: Any) -> tuple[Path | None, str | None]:
        captured["force_http_fallback"] = kwargs["force_http_fallback"]
        captured["client_path"] = kwargs["client_path"]
        return fallback, None

    monkeypatch.setattr(codex_cmd, "resolve_codex_addons_and_ca", fake_resolve_codex_addons_and_ca)

    with pytest.raises(Exit):
        codex_cmd.run_codex(
            directory=tmp_path,
            codex_passthrough=[],
            proxy_port=9000,
            web_port=9001,
            storage_dir=tmp_path / "storage",
            home_dir=None,
            codex_bin=None,
            no_codex=False,
            debug=False,
            force_http_fallback=True,
            print_command=True,
            require_addon=lambda: addon,
            require_force_http_fallback_addon=lambda: fallback,
            resolve_mitmdump=lambda: "/bin/mitmdump",
            which=lambda name: "/bin/codex" if name == "codex" else "/bin/mitmdump",
            port_in_use=lambda port: False,
            allocate_port_pair=lambda: (9000, 9001),
            resolve_codex_ca_certificate=lambda **_: tmp_path / "ca.pem",
            print_client_banner=lambda **_: None,
            run_client_with_retry=lambda **_: None,
        )

    assert captured == {"force_http_fallback": True, "client_path": "/bin/codex"}


async def test_launch_fields_carrier_reaches_owned_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from transport_matters import addon_runtime
    from transport_matters.addon_runtime import _register_owned_cursor
    from transport_matters.config import Settings

    captured: dict[str, Any] = {}
    runtime_template = {"template_id": "codex/base", "template_home": "/templates/codex"}

    class FakeAdapter:
        provider = "codex"
        cli = "codex"

        async def bind(self, run: Any) -> SessionBinding:
            return SessionBinding(
                session_id="session-1",
                provider=self.provider,
                run_id=run.run_id,
                cwd=run.cwd,
                workspace_slug=run.workspace_slug,
                workspace_hash=run.workspace_hash,
                started_at=run.started_at,
                cli=self.cli,
                native_session_id=run.native_session_id,
            )

    async def fake_register_session_cursor(
        _tailer: Any, _adapter: Any, binding: SessionBinding
    ) -> None:
        captured["runtime_template"] = cast("Any", binding).runtime_template
        captured["source_descriptor"] = binding.source_descriptor

    monkeypatch.setattr(addon_runtime, "get_adapter", lambda _cli: FakeAdapter())
    monkeypatch.setattr(
        addon_runtime,
        "register_session_cursor",
        fake_register_session_cursor,
    )

    settings = Settings(
        run_id="run-1",
        cwd=tmp_path,
        cli="codex",
        owned_native_session_id="native-1",
        owned_source_descriptor="descriptor-1",
        launch_fields={"runtime_template": runtime_template},
    )
    await _register_owned_cursor(cast("Any", object()), settings, "2026-06-15T12:00:00+00:00")

    assert captured == {
        "runtime_template": runtime_template,
        "source_descriptor": "descriptor-1",
    }


async def test_register_session_cursor_preserves_dynamic_launch_fields(tmp_path: Path) -> None:
    from transport_matters.index.tailer import register_session_cursor

    runtime_template = {"template_id": "codex/base", "template_home": "/templates/codex"}
    descriptor = encode_source_descriptor(
        FileTailSource(path=str(tmp_path / "rollout.jsonl"), format="codex_rollout")
    )
    binding = SessionBinding(
        session_id="session-1",
        provider="codex",
        run_id="run-1",
        cwd=str(tmp_path),
        workspace_slug="workspace",
        workspace_hash="hash",
        started_at="2026-06-15T12:00:00+00:00",
        cli="codex",
        native_session_id="native-1",
        source_descriptor=descriptor,
    ).model_copy(update={"runtime_template": runtime_template})

    class FakeAdapter:
        provider = "codex"
        cli = "codex"

        async def bind(self, _run: Any) -> SessionBinding:
            return binding.model_copy(update={"runtime_template": None})

    class FakeTailer:
        def __init__(self) -> None:
            self.cursor: Any = None

        def register(self, cursor: Any) -> None:
            self.cursor = cursor

    tailer = FakeTailer()
    await register_session_cursor(cast("Any", tailer), cast("Any", FakeAdapter()), binding)

    assert tailer.cursor is not None
    assert tailer.cursor.binding.runtime_template == runtime_template
