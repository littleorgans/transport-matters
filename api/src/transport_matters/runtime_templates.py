"""Runtime template value objects shared across API, run management, and CLI code."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

type RuntimeTemplateVendor = Literal["anthropic", "openai"]
type RuntimeTemplateHarness = Literal["claude", "codex", "opencode", "pi"]
type RuntimeTemplateEffort = Literal["low", "medium", "high", "xhigh"]

RUNTIME_TEMPLATE_HARNESSES: tuple[RuntimeTemplateHarness, ...] = (
    "claude",
    "codex",
    "opencode",
    "pi",
)
RUNTIME_TEMPLATE_VENDORS: tuple[RuntimeTemplateVendor, ...] = ("anthropic", "openai")
HARNESS_VENDOR_COMPATIBILITY: MappingProxyType[
    RuntimeTemplateHarness, tuple[RuntimeTemplateVendor, ...]
] = MappingProxyType(
    {
        "claude": ("anthropic",),
        "codex": ("openai",),
        "opencode": ("anthropic", "openai"),
        # TODO(stuart): confirm pi vendor set.
        "pi": ("anthropic", "openai"),
    }
)


class RuntimeTemplateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecommendedModelDefault(RuntimeTemplateModel):
    harness: RuntimeTemplateHarness | None = None
    vendor: RuntimeTemplateVendor | None = None


class RecommendedVendorModel(RuntimeTemplateModel):
    model: str | None = None
    effort: RuntimeTemplateEffort | None = None


class RecommendedModel(RuntimeTemplateModel):
    default: RecommendedModelDefault | None = None
    by_vendor: dict[RuntimeTemplateVendor, RecommendedVendorModel] | None = None


class RuntimeTemplateCapabilities(RuntimeTemplateModel):
    schema_version: Literal[2]
    vendors: tuple[RuntimeTemplateVendor, ...]
    required_capabilities: tuple[str, ...]
    recommended_model: RecommendedModel | None
    generated_from: str


class RuntimeTemplateSummary(RuntimeTemplateModel):
    name: str
    vendors: tuple[RuntimeTemplateVendor, ...]
    required_capabilities: tuple[str, ...]
    recommended_model: RecommendedModel | None


@dataclass(frozen=True, slots=True)
class RuntimeTemplateRef:
    template_id: str
    harness: str
    template_home: Path
    provenance: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class RuntimeTemplateProvenance:
    template_id: str
    template_home: Path
    provenance: Mapping[str, str]

    def as_launch_field(self) -> dict[str, str]:
        field = {
            "template_id": self.template_id,
            "template_home": str(self.template_home),
        }
        field.update(self.provenance)
        return field


@dataclass(frozen=True, slots=True)
class RuntimeTemplateListing:
    name: str
    capabilities: RuntimeTemplateCapabilities
    template_home: Path
    provenance: Mapping[str, str]

    def summary(self) -> RuntimeTemplateSummary:
        return RuntimeTemplateSummary(
            name=self.name,
            vendors=self.capabilities.vendors,
            required_capabilities=self.capabilities.required_capabilities,
            recommended_model=self.capabilities.recommended_model,
        )


def runtime_template_supports_harness(
    capabilities: RuntimeTemplateCapabilities,
    harness: RuntimeTemplateHarness,
) -> bool:
    return not set(capabilities.vendors).isdisjoint(HARNESS_VENDOR_COMPATIBILITY[harness])


def compatible_runtime_template_harnesses(
    capabilities: RuntimeTemplateCapabilities,
) -> tuple[RuntimeTemplateHarness, ...]:
    return tuple(
        harness
        for harness in RUNTIME_TEMPLATE_HARNESSES
        if runtime_template_supports_harness(capabilities, harness)
    )
