"""Tests for the core CLI capabilities provider."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from transport_matters.capabilities import detect_cli, detect_clis, resolve_cli_binary


def _write_version_cli(path: Path, output: str) -> Path:
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_detect_clis_reports_present_versions(tmp_path: Path) -> None:
    claude = _write_version_cli(tmp_path / "claude", "claude 1.2.3")
    codex = _write_version_cli(tmp_path / "codex", "codex 4.5.6")
    paths = {"claude": str(claude), "codex": str(codex)}

    result = detect_clis(which=paths.get)

    assert result["claude"].installed is True
    assert result["claude"].path == str(claude)
    assert result["claude"].version == "claude 1.2.3"
    assert result["codex"].installed is True
    assert result["codex"].path == str(codex)
    assert result["codex"].version == "codex 4.5.6"


def test_detect_clis_reports_absent_without_version_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("missing CLIs must not run version probes")

    monkeypatch.setattr(subprocess, "run", fail_run)

    result = detect_clis(which=lambda _name: None)

    assert result["claude"].installed is False
    assert result["claude"].path is None
    assert result["claude"].version is None
    assert result["codex"].installed is False
    assert result["codex"].path is None
    assert result["codex"].version is None


def test_detect_cli_timeout_reports_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["claude", "--version"], timeout=0.01)

    monkeypatch.setattr(subprocess, "run", timeout_run)

    result = detect_cli("claude", which=lambda _name: "/tmp/fake-claude")

    assert result.installed is False
    assert result.path is None
    assert result.version is None


def test_resolve_cli_binary_preserves_launch_override_behavior(tmp_path: Path) -> None:
    override = tmp_path / "custom-claude"

    result = resolve_cli_binary(
        name="claude",
        bin_override=override,
        which=lambda _name: None,
    )

    assert result == str(override)


def test_resolve_cli_binary_honors_disabled_flag(tmp_path: Path) -> None:
    result = resolve_cli_binary(
        name="codex",
        bin_override=tmp_path / "codex",
        disabled=True,
        which=lambda _name: "/bin/codex",
    )

    assert result is None
