from __future__ import annotations

from pathlib import Path

import pytest

from transport_matters import env_keys
from transport_matters.runtime_registry import (
    list_runtime_templates,
    read_runtime_template_capabilities,
    resolve_runtime_template,
    runtime_template_roots,
)
from transport_matters.runtime_templates import (
    HARNESS_VENDOR_COMPATIBILITY,
    RUNTIME_TEMPLATE_HARNESSES,
    compatible_runtime_template_harnesses,
    runtime_template_supports_harness,
)


def test_resolve_runtime_template_from_agent_runtimes_registry(tmp_path: Path) -> None:
    template = tmp_path / ".agent-runtimes" / "runtimes" / "base"
    template.mkdir(parents=True)
    (template / "runtime.toml").write_text("[runtime]\n", encoding="utf-8")
    (template / ".git").mkdir()

    ref = resolve_runtime_template("base", "codex", env={"HOME": str(tmp_path)})

    assert ref.template_id == "base"
    assert ref.harness == "codex"
    assert ref.template_home == template.resolve()
    assert ref.provenance == {
        "registry_source": "agent-runtimes",
        "registry_root": str((tmp_path / ".agent-runtimes" / "runtimes").resolve()),
    }


def test_resolve_runtime_template_falls_back_to_tm_fleet_root(tmp_path: Path) -> None:
    template = tmp_path / "tm-home" / "runtimes" / "codex-base"
    template.mkdir(parents=True)

    ref = resolve_runtime_template(
        "codex-base",
        "codex",
        env={"HOME": str(tmp_path / "home"), env_keys.HOME: str(tmp_path / "tm-home")},
    )

    assert ref.template_id == "codex-base"
    assert ref.template_home == template.resolve()
    assert ref.provenance == {
        "registry_source": "tm-fleet",
        "registry_root": str((tmp_path / "tm-home" / "runtimes").resolve()),
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


def test_runtime_template_roots_enumerate_design_specified_roots(tmp_path: Path) -> None:
    roots = runtime_template_roots(
        env={"HOME": str(tmp_path / "home"), env_keys.HOME: str(tmp_path / "tm-home")}
    )

    assert [(root.source, root.path) for root in roots] == [
        (
            "agent-runtimes",
            tmp_path / "home" / ".agent-runtimes" / "runtimes",
        ),
        ("tm-fleet", tmp_path / "tm-home" / "runtimes"),
    ]


def test_list_runtime_templates_reads_optional_and_effort_only_fields(tmp_path: Path) -> None:
    template = _template_dir(tmp_path, "codebase-mapper")
    _write_capabilities(
        template,
        """
        {
          "schema_version": 2,
          "vendors": ["anthropic", "openai"],
          "required_capabilities": [],
          "recommended_model": {
            "default": {"harness": "claude", "vendor": "anthropic"},
            "by_vendor": {
              "anthropic": {"effort": "xhigh"},
              "openai": {"effort": "xhigh"}
            }
          },
          "generated_from": "digest"
        }
        """,
    )

    listed = list_runtime_templates(env={"HOME": str(tmp_path)})

    assert len(listed) == 1
    assert listed[0].model_dump(mode="json", exclude_none=True) == {
        "name": "codebase-mapper",
        "vendors": ["anthropic", "openai"],
        "required_capabilities": [],
        "recommended_model": {
            "default": {"harness": "claude", "vendor": "anthropic"},
            "by_vendor": {
                "anthropic": {"effort": "xhigh"},
                "openai": {"effort": "xhigh"},
            },
        },
    }


def test_list_runtime_templates_accepts_missing_recommended_model_parts(tmp_path: Path) -> None:
    template = _template_dir(tmp_path, "minimal")
    _write_capabilities(
        template,
        """
        {
          "schema_version": 2,
          "vendors": ["anthropic"],
          "required_capabilities": [],
          "recommended_model": {"by_vendor": {"anthropic": {"model": "claude-opus-4-8"}}},
          "generated_from": "digest"
        }
        """,
    )

    listed = list_runtime_templates(env={"HOME": str(tmp_path)})

    assert listed[0].model_dump(mode="json", exclude_none=True) == {
        "name": "minimal",
        "vendors": ["anthropic"],
        "required_capabilities": [],
        "recommended_model": {
            "by_vendor": {"anthropic": {"model": "claude-opus-4-8"}},
        },
    }


def test_list_runtime_templates_preserves_null_recommended_model(tmp_path: Path) -> None:
    template = _template_dir(tmp_path, "native")
    _write_capabilities(
        template,
        """
        {
          "schema_version": 2,
          "vendors": ["anthropic", "openai"],
          "required_capabilities": [],
          "recommended_model": null,
          "generated_from": "digest"
        }
        """,
    )

    listed = list_runtime_templates(env={"HOME": str(tmp_path)})

    assert listed[0].model_dump(mode="json")["recommended_model"] is None


def test_list_runtime_templates_reads_openai_only_template(tmp_path: Path) -> None:
    template = _template_dir(tmp_path, "imagegen")
    _write_capabilities(
        template,
        """
        {
          "schema_version": 2,
          "vendors": ["openai"],
          "required_capabilities": ["image-generation"],
          "recommended_model": {
            "default": {"harness": "codex", "vendor": "openai"},
            "by_vendor": {"openai": {"model": "gpt-5.5", "effort": "xhigh"}}
          },
          "generated_from": "digest"
        }
        """,
    )

    listed = list_runtime_templates(env={"HOME": str(tmp_path)})

    assert listed[0].vendors == ("openai",)
    assert listed[0].required_capabilities == ("image-generation",)


def test_list_runtime_templates_reads_dual_vendor_template(tmp_path: Path) -> None:
    template = _template_dir(tmp_path, "research")
    _write_capabilities(
        template,
        """
        {
          "schema_version": 2,
          "vendors": ["anthropic", "openai"],
          "required_capabilities": [],
          "recommended_model": {
            "default": {"harness": "claude", "vendor": "anthropic"},
            "by_vendor": {
              "anthropic": {"model": "claude-opus-4-8", "effort": "xhigh"},
              "openai": {"model": "gpt-5.5", "effort": "xhigh"}
            }
          },
          "generated_from": "digest"
        }
        """,
    )

    listed = list_runtime_templates(env={"HOME": str(tmp_path)})

    assert listed[0].vendors == ("anthropic", "openai")


def test_list_runtime_templates_walks_nested_templates(tmp_path: Path) -> None:
    template = _template_dir(tmp_path, "team/codex")
    _write_capabilities(
        template,
        """
        {
          "schema_version": 2,
          "vendors": ["openai"],
          "required_capabilities": [],
          "recommended_model": null,
          "generated_from": "digest"
        }
        """,
    )

    listed = list_runtime_templates(env={"HOME": str(tmp_path)})

    assert [template.name for template in listed] == ["team/codex"]


def test_list_runtime_templates_missing_roots_return_empty(tmp_path: Path) -> None:
    assert list_runtime_templates(env={"HOME": str(tmp_path)}) == ()


def test_list_runtime_templates_uses_first_root_for_duplicate_names(tmp_path: Path) -> None:
    user_template = _template_dir(tmp_path, "shared")
    fleet_template = tmp_path / ".transport-matters" / "runtimes" / "shared"
    fleet_template.mkdir(parents=True)
    (fleet_template / "runtime.toml").write_text("[runtime]\n", encoding="utf-8")
    _write_capabilities(
        user_template,
        """
        {
          "schema_version": 2,
          "vendors": ["openai"],
          "required_capabilities": ["image-generation"],
          "recommended_model": null,
          "generated_from": "user"
        }
        """,
    )
    _write_capabilities(
        fleet_template,
        """
        {
          "schema_version": 2,
          "vendors": ["anthropic"],
          "required_capabilities": [],
          "recommended_model": null,
          "generated_from": "fleet"
        }
        """,
    )

    listed = list_runtime_templates(env={"HOME": str(tmp_path)})

    assert len(listed) == 1
    assert listed[0].vendors == ("openai",)


def test_read_runtime_template_capabilities_rejects_unknown_shape(tmp_path: Path) -> None:
    template = _template_dir(tmp_path, "bad")
    (template / "capabilities.json").write_text(
        """
        {
          "schema_version": 2,
          "vendors": ["openai"],
          "required_capabilities": [],
          "recommended_model": null,
          "generated_from": "digest",
          "surprise": true
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid runtime template capabilities"):
        read_runtime_template_capabilities(template)


def test_compatibility_map_has_matching_vendor_for_each_harness(tmp_path: Path) -> None:
    template = _template_dir(tmp_path, "research")
    _write_capabilities(
        template,
        """
        {
          "schema_version": 2,
          "vendors": ["anthropic", "openai"],
          "required_capabilities": [],
          "recommended_model": null,
          "generated_from": "digest"
        }
        """,
    )

    capabilities = read_runtime_template_capabilities(template)

    assert set(HARNESS_VENDOR_COMPATIBILITY) == set(RUNTIME_TEMPLATE_HARNESSES)
    assert all(
        set(HARNESS_VENDOR_COMPATIBILITY[harness]) & set(capabilities.vendors)
        for harness in RUNTIME_TEMPLATE_HARNESSES
    )
    assert compatible_runtime_template_harnesses(capabilities) == RUNTIME_TEMPLATE_HARNESSES


def test_compatibility_map_filters_openai_only_template(tmp_path: Path) -> None:
    template = _template_dir(tmp_path, "imagegen")
    _write_capabilities(
        template,
        """
        {
          "schema_version": 2,
          "vendors": ["openai"],
          "required_capabilities": ["image-generation"],
          "recommended_model": null,
          "generated_from": "digest"
        }
        """,
    )

    capabilities = read_runtime_template_capabilities(template)

    assert not runtime_template_supports_harness(capabilities, "claude")
    assert runtime_template_supports_harness(capabilities, "codex")
    assert runtime_template_supports_harness(capabilities, "opencode")
    assert runtime_template_supports_harness(capabilities, "pi")


def _template_dir(tmp_path: Path, name: str) -> Path:
    template = tmp_path / ".agent-runtimes" / "runtimes" / Path(*name.split("/"))
    template.mkdir(parents=True)
    (template / "runtime.toml").write_text("[runtime]\n", encoding="utf-8")
    return template


def _write_capabilities(template: Path, content: str) -> None:
    (template / "capabilities.json").write_text(content, encoding="utf-8")
