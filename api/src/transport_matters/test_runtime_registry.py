from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from transport_matters.runtime_registry import resolve_runtime_template

if TYPE_CHECKING:
    from pathlib import Path


def test_resolve_runtime_template_from_agent_runtimes_registry(tmp_path: Path) -> None:
    template = tmp_path / ".agent-runtimes" / "runtimes" / "base"
    template.mkdir(parents=True)
    (template / "runtime.toml").write_text("[runtime]\n", encoding="utf-8")
    (template / ".git").mkdir()

    ref = resolve_runtime_template("base", "codex", env={"HOME": str(tmp_path)})

    assert ref.template_id == "base"
    assert ref.client_name == "codex"
    assert ref.template_home == template.resolve()
    assert ref.provenance == {
        "registry_source": "agent-runtimes",
        "registry_root": str((tmp_path / ".agent-runtimes" / "runtimes").resolve()),
    }


def test_resolve_runtime_template_allows_nested_relative_names(tmp_path: Path) -> None:
    template = tmp_path / ".agent-runtimes" / "runtimes" / "team" / "codex"
    template.mkdir(parents=True)

    ref = resolve_runtime_template("team/codex", "codex", env={"HOME": str(tmp_path)})

    assert ref.template_id == "team/codex"
    assert ref.template_home == template.resolve()


@pytest.mark.parametrize("name", ["", "  ", ".", "../escape", "/tmp/template", "team/../escape"])
def test_resolve_runtime_template_rejects_unsafe_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match=r"invalid runtime template name|escapes"):
        resolve_runtime_template(name, "codex", env={"HOME": str(tmp_path)})


def test_resolve_runtime_template_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        resolve_runtime_template("missing", "codex", env={"HOME": str(tmp_path)})
