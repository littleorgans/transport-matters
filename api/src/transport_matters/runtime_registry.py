"""Thin consumer for the external ``.agent-runtimes`` registry."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from transport_matters.runtime_templates import RuntimeTemplateRef

if TYPE_CHECKING:
    from collections.abc import Mapping

_AGENT_RUNTIMES_DIR = ".agent-runtimes"
_RUNTIMES_DIR = "runtimes"
_REGISTRY_SOURCE = "agent-runtimes"


def resolve_runtime_template(
    name: str,
    client_name: str,
    *,
    env: Mapping[str, str],
) -> RuntimeTemplateRef:
    """Resolve a named external runtime template for one client launch."""
    template_id = _validated_template_name(name)
    registry_root = _registry_root(env)
    resolved_root = registry_root.resolve(strict=False)
    template_home = (registry_root / Path(*PurePosixPath(template_id).parts)).resolve(strict=False)
    if not template_home.is_relative_to(resolved_root):
        raise ValueError(f"runtime template {template_id!r} escapes the registry root")
    if not template_home.exists():
        raise ValueError(f"runtime template {template_id!r} does not exist under {resolved_root}")
    if not template_home.is_dir():
        raise ValueError(
            f"runtime template {template_id!r} is not a directory under {resolved_root}"
        )
    return RuntimeTemplateRef(
        template_id=template_id,
        client_name=client_name,
        template_home=template_home,
        provenance={
            "registry_source": _REGISTRY_SOURCE,
            "registry_root": str(resolved_root),
        },
    )


def _registry_root(env: Mapping[str, str]) -> Path:
    home = Path(env.get("HOME", "~")).expanduser()
    return home / _AGENT_RUNTIMES_DIR / _RUNTIMES_DIR


def _validated_template_name(name: str) -> str:
    stripped = name.strip()
    path = PurePosixPath(stripped)
    if (
        not stripped
        or stripped in {".", ".."}
        or path.is_absolute()
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise ValueError(f"invalid runtime template name: {name!r}")
    return path.as_posix()
