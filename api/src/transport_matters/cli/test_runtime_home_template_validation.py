from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from transport_matters.cli.runtime_home import (
    RuntimeHomeMode,
    RuntimeTemplateRef,
    plan_runtime_home,
)
from transport_matters.launch_environment import HARNESS_NAME_CLAUDE, HARNESS_NAME_CODEX

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("harness", "secret_name"),
    [
        (HARNESS_NAME_CLAUDE, ".credentials.json"),
        (HARNESS_NAME_CODEX, "auth.json"),
    ],
)
def test_template_credential_files_are_rejected(
    tmp_path: Path,
    harness: str,
    secret_name: str,
) -> None:
    template = tmp_path / "template"
    template.mkdir()
    (template / secret_name).write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="credential"):
        plan_runtime_home(
            harness,
            home_dir=None,
            runtime_template=RuntimeTemplateRef(
                template_id="client/base",
                harness=harness,
                template_home=template,
                provenance={},
            ),
            runtime_home_root=tmp_path / "run" / "runtime-home",
            client_path=f"/bin/{harness}",
            env={},
            use_runtime_overlay=True,
        )


@pytest.mark.parametrize("field_name", ["oauthAccount", "userID"])
def test_claude_template_account_fields_are_rejected(
    tmp_path: Path,
    field_name: str,
) -> None:
    template = tmp_path / "template"
    template.mkdir()
    (template / ".claude.json").write_text(
        json.dumps({field_name: "secret"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=field_name):
        plan_runtime_home(
            HARNESS_NAME_CLAUDE,
            home_dir=None,
            runtime_template=RuntimeTemplateRef(
                template_id="claude/base",
                harness=HARNESS_NAME_CLAUDE,
                template_home=template,
                provenance={},
            ),
            runtime_home_root=tmp_path / "run" / "runtime-home",
            client_path="/bin/claude",
            env={},
            use_runtime_overlay=True,
        )


@pytest.mark.parametrize(
    "config_text",
    (
        '[auth]\ntoken = "secret"\n',
        '[provider]\nOPENAI_API_KEY = "secret"\n',
    ),
)
def test_codex_template_config_auth_material_is_rejected(
    tmp_path: Path,
    config_text: str,
) -> None:
    template = tmp_path / "template"
    template.mkdir()
    (template / "config.toml").write_text(config_text, encoding="utf-8")

    with pytest.raises(ValueError, match="auth material"):
        plan_runtime_home(
            HARNESS_NAME_CODEX,
            home_dir=None,
            runtime_template=RuntimeTemplateRef(
                template_id="codex/base",
                harness=HARNESS_NAME_CODEX,
                template_home=template,
                provenance={},
            ),
            runtime_home_root=tmp_path / "run" / "runtime-home",
            client_path="/bin/codex",
            env={},
            use_runtime_overlay=True,
        )


def test_codex_template_config_benign_auth_like_keys_are_allowed(
    tmp_path: Path,
) -> None:
    template = tmp_path / "template"
    template.mkdir()
    (template / "config.toml").write_text(
        '[profile]\nauthor = "Stuart"\naccount_name = "work"\n',
        encoding="utf-8",
    )

    plan = plan_runtime_home(
        HARNESS_NAME_CODEX,
        home_dir=None,
        runtime_template=RuntimeTemplateRef(
            template_id="codex/base",
            harness=HARNESS_NAME_CODEX,
            template_home=template,
            provenance={},
        ),
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path="/bin/codex",
        env={},
        use_runtime_overlay=True,
    )

    assert plan.mode == RuntimeHomeMode.TEMPLATE


def test_runtime_template_missing_root_is_rejected(tmp_path: Path) -> None:
    missing_template = tmp_path / "missing-template"

    with pytest.raises(
        ValueError,
        match=f"runtime template {missing_template} does not exist",
    ):
        plan_runtime_home(
            HARNESS_NAME_CODEX,
            home_dir=None,
            runtime_template=RuntimeTemplateRef(
                template_id="codex/base",
                harness=HARNESS_NAME_CODEX,
                template_home=missing_template,
                provenance={},
            ),
            runtime_home_root=tmp_path / "run" / "runtime-home",
            client_path="/bin/codex",
            env={},
            use_runtime_overlay=True,
        )


@pytest.mark.parametrize(
    ("harness", "seed_file"),
    [
        (HARNESS_NAME_CLAUDE, ".claude.json"),
        (HARNESS_NAME_CODEX, "config.toml"),
    ],
)
def test_template_unknown_top_level_entries_do_not_fail_planning(
    tmp_path: Path,
    harness: str,
    seed_file: str,
) -> None:
    template = tmp_path / "template"
    template.mkdir()
    seed_content = 'model = "gpt-5-codex"\n' if seed_file == "config.toml" else "{}\n"
    (template / seed_file).write_text(seed_content, encoding="utf-8")
    (template / "mystery-state").mkdir()

    plan = plan_runtime_home(
        harness,
        home_dir=None,
        runtime_template=RuntimeTemplateRef(
            template_id="client/base",
            harness=harness,
            template_home=template,
            provenance={},
        ),
        runtime_home_root=tmp_path / "run" / "runtime-home",
        client_path=f"/bin/{harness}",
        env={},
        use_runtime_overlay=True,
    )

    assert plan.mode == RuntimeHomeMode.TEMPLATE
