from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from transport_matters.cli.home_seed import prepare_runtime_home_overlay
from transport_matters.launch_environment import HARNESS_NAME_CLAUDE, HARNESS_NAME_CODEX

if TYPE_CHECKING:
    from pathlib import Path


def test_claude_runtime_overlay_links_credentials_from_auth_source(
    tmp_path: Path,
) -> None:
    content = tmp_path / "template-claude"
    content.mkdir()
    (content / ".credentials.json").write_bytes(b'{"token":"template"}\n')
    native = tmp_path / "native-claude"
    native.mkdir()
    credentials = native / ".credentials.json"
    credentials.write_bytes(b'{"token":"native"}\n')
    runtime = tmp_path / "runtime" / "claude"
    workdir = tmp_path / "project"
    workdir.mkdir()

    prepare_runtime_home_overlay(
        HARNESS_NAME_CLAUDE,
        source_home_dir=content,
        auth_source_home_dir=native,
        runtime_home_dir=runtime,
        working_dir=workdir,
        env={},
    )

    credentials_link = runtime / ".credentials.json"
    assert credentials_link.is_symlink()
    assert credentials_link.resolve() == credentials.resolve()
    assert credentials_link.read_bytes() == b'{"token":"native"}\n'


@pytest.mark.parametrize(
    ("harness", "credential_name", "env_key"),
    [
        (HARNESS_NAME_CODEX, "auth.json", "CODEX_HOME"),
        (HARNESS_NAME_CLAUDE, ".credentials.json", "CLAUDE_CONFIG_DIR"),
    ],
)
def test_runtime_overlay_skips_missing_native_credentials_without_content_fallback(
    tmp_path: Path,
    harness: str,
    credential_name: str,
    env_key: str,
) -> None:
    content = tmp_path / f"content-{harness}"
    content.mkdir()
    (content / credential_name).write_text("template secret\n", encoding="utf-8")
    auth_source = tmp_path / f"native-{harness}"
    auth_source.mkdir()
    runtime = tmp_path / "runtime" / harness
    workdir = tmp_path / "project"
    workdir.mkdir()

    prepare_runtime_home_overlay(
        harness,
        source_home_dir=content,
        auth_source_home_dir=auth_source,
        runtime_home_dir=runtime,
        working_dir=workdir,
        env={env_key: str(content)},
    )

    assert not (runtime / credential_name).exists()
    assert not (runtime / credential_name).is_symlink()


@pytest.mark.parametrize(
    ("harness", "credential_name", "env_key"),
    [
        (HARNESS_NAME_CODEX, "auth.json", "CODEX_HOME"),
        (HARNESS_NAME_CLAUDE, ".credentials.json", "CLAUDE_CONFIG_DIR"),
    ],
)
def test_runtime_overlay_credential_teardown_leaves_native_file(
    tmp_path: Path,
    harness: str,
    credential_name: str,
    env_key: str,
) -> None:
    content = tmp_path / f"content-{harness}"
    content.mkdir()
    auth_source = tmp_path / f"native-{harness}"
    auth_source.mkdir()
    native_credential = auth_source / credential_name
    native_credential.write_text("native sentinel\n", encoding="utf-8")
    runtime_root = tmp_path / "runtime"
    runtime = runtime_root / harness
    workdir = tmp_path / "project"
    workdir.mkdir()

    prepare_runtime_home_overlay(
        harness,
        source_home_dir=content,
        auth_source_home_dir=auth_source,
        runtime_home_dir=runtime,
        working_dir=workdir,
        env={env_key: str(content)},
    )

    credential_link = runtime / credential_name
    assert credential_link.is_symlink()
    assert credential_link.resolve() == native_credential.resolve()
    credential_link.write_text("rotated sentinel\n", encoding="utf-8")
    assert native_credential.read_text(encoding="utf-8") == "rotated sentinel\n"

    shutil.rmtree(runtime_root)

    assert native_credential.read_text(encoding="utf-8") == "rotated sentinel\n"
