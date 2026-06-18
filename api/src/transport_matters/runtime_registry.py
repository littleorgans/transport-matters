"""Thin consumer for runtime template registries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from pydantic import ValidationError

from transport_matters import env_keys
from transport_matters.runtime_templates import (
    RuntimeTemplateCapabilities,
    RuntimeTemplateListing,
    RuntimeTemplateRef,
    RuntimeTemplateSummary,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_AGENT_RUNTIMES_DIR = ".agent-runtimes"
_TRANSPORT_MATTERS_DIR = ".transport-matters"
_RUNTIMES_DIR = "runtimes"
_CAPABILITIES_FILENAME = "capabilities.json"
_RUNTIME_MANIFEST_FILENAME = "runtime.toml"
_AGENT_RUNTIMES_SOURCE = "agent-runtimes"
_TM_FLEET_SOURCE = "tm-fleet"


class RuntimeTemplateRegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeTemplateRoot:
    source: str
    path: Path


def resolve_runtime_template(
    name: str,
    harness: str,
    *,
    env: Mapping[str, str],
) -> RuntimeTemplateRef:
    """Resolve a named external runtime template for one client launch."""
    template_id = _validated_template_name(name)
    roots = runtime_template_roots(env)
    for root in roots:
        ref = _resolve_runtime_template_in_root(template_id, harness, root)
        if ref is not None:
            return ref

    formatted_roots = ", ".join(str(root.path.resolve(strict=False)) for root in roots)
    raise ValueError(f"runtime template {template_id!r} does not exist under {formatted_roots}")


def list_runtime_templates(
    *,
    env: Mapping[str, str],
) -> tuple[RuntimeTemplateSummary, ...]:
    """List browsable runtime templates from every design specified root."""
    seen_names: set[str] = set()
    summaries: list[RuntimeTemplateSummary] = []
    for root in runtime_template_roots(env):
        for listing in _list_runtime_templates_in_root(root):
            if listing.name in seen_names:
                continue
            seen_names.add(listing.name)
            summaries.append(listing.summary())
    return tuple(summaries)


def read_runtime_template_capabilities(template_home: Path) -> RuntimeTemplateCapabilities:
    """Parse one generated runtime capabilities artifact."""
    capabilities_path = template_home / _CAPABILITIES_FILENAME
    try:
        raw: object = json.loads(capabilities_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeTemplateRegistryError(
            f"could not read runtime template capabilities at {capabilities_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeTemplateRegistryError(
            f"invalid runtime template capabilities JSON at {capabilities_path}: {exc}"
        ) from exc

    try:
        return RuntimeTemplateCapabilities.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeTemplateRegistryError(
            f"invalid runtime template capabilities at {capabilities_path}: {exc}"
        ) from exc


def runtime_template_roots(env: Mapping[str, str]) -> tuple[RuntimeTemplateRoot, ...]:
    """Return the ordered runtime template registry roots."""
    home = _home_dir(env)
    transport_home = _transport_matters_home(env, home)
    return (
        RuntimeTemplateRoot(
            source=_AGENT_RUNTIMES_SOURCE,
            path=home / _AGENT_RUNTIMES_DIR / _RUNTIMES_DIR,
        ),
        RuntimeTemplateRoot(
            source=_TM_FLEET_SOURCE,
            path=transport_home / _RUNTIMES_DIR,
        ),
    )


def _resolve_runtime_template_in_root(
    template_id: str,
    harness: str,
    root: RuntimeTemplateRoot,
) -> RuntimeTemplateRef | None:
    resolved_root = root.path.resolve(strict=False)
    template_home = (root.path / Path(*PurePosixPath(template_id).parts)).resolve(strict=False)
    if not template_home.is_relative_to(resolved_root):
        raise ValueError(f"runtime template {template_id!r} escapes the registry root")
    if not template_home.exists():
        return None
    if not template_home.is_dir():
        raise ValueError(
            f"runtime template {template_id!r} is not a directory under {resolved_root}"
        )
    return RuntimeTemplateRef(
        template_id=template_id,
        harness=harness,
        template_home=template_home,
        provenance={
            "registry_source": root.source,
            "registry_root": str(resolved_root),
        },
    )


def _list_runtime_templates_in_root(
    root: RuntimeTemplateRoot,
) -> tuple[RuntimeTemplateListing, ...]:
    if not root.path.is_dir():
        return ()
    resolved_root = root.path.resolve(strict=False)
    listings: list[RuntimeTemplateListing] = []
    for capabilities_path in sorted(root.path.rglob(_CAPABILITIES_FILENAME)):
        template_home = capabilities_path.parent
        if not (template_home / _RUNTIME_MANIFEST_FILENAME).is_file():
            continue
        resolved_template_home = template_home.resolve(strict=False)
        if not resolved_template_home.is_relative_to(resolved_root):
            continue
        name = _validated_template_name(template_home.relative_to(root.path).as_posix())
        capabilities = read_runtime_template_capabilities(template_home)
        listings.append(
            RuntimeTemplateListing(
                name=name,
                capabilities=capabilities,
                template_home=resolved_template_home,
                provenance={
                    "registry_source": root.source,
                    "registry_root": str(resolved_root),
                },
            )
        )
    return tuple(sorted(listings, key=lambda listing: listing.name))


def _home_dir(env: Mapping[str, str]) -> Path:
    return Path(env.get("HOME", "~")).expanduser()


def _transport_matters_home(env: Mapping[str, str], home: Path) -> Path:
    override = env.get(env_keys.HOME)
    if override:
        return Path(override).expanduser()
    return home / _TRANSPORT_MATTERS_DIR


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
