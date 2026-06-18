"""Runtime template value objects shared across API, run management, and CLI code."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


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
