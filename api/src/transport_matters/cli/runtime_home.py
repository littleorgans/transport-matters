"""Runtime home planning shared by captured and Codex launches."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from transport_matters.cli.home_seed import (
    RuntimeHomeOverlay,
    prepare_runtime_home_overlay,
    prepare_runtime_home_template_overlay,
    resolve_source_home_dir,
    validate_runtime_home_template,
)
from transport_matters.launch_environment import CLIENT_NAME_CLAUDE, CLIENT_NAME_CODEX

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class RuntimeHomeMode(StrEnum):
    NATIVE = "native"
    MANUAL = "manual"
    TEMPLATE = "template"
    PROXY_ONLY = "proxy_only"


@dataclass(frozen=True, slots=True)
class RuntimeTemplateRef:
    template_id: str
    client_name: str
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
class RuntimeHomePlan:
    client_name: str
    content_source: Path | None
    auth_source: Path | None
    hook_trust_source: Path | None
    child_home: Path | None
    descriptor_home: Path | None
    template_provenance: RuntimeTemplateProvenance | None
    mode: RuntimeHomeMode

    @property
    def runtime_home_dir(self) -> Path | None:
        if self.child_home is None or self.child_home == self.content_source:
            return None
        return self.child_home

    @property
    def launch_fields(self) -> dict[str, Any]:  # Any: launch metadata is a JSON env carrier.
        if self.template_provenance is None:
            return {}
        return {"runtime_template": self.template_provenance.as_launch_field()}


def plan_runtime_home(
    client_name: str,
    *,
    home_dir: Path | None,
    runtime_template: RuntimeTemplateRef | None,
    runtime_home_root: Path | None,
    client_path: str | None,
    env: Mapping[str, str],
    use_runtime_overlay: bool,
) -> RuntimeHomePlan:
    """Plan source, child, and descriptor homes for a managed launch."""
    if client_path is None:
        manual_home = home_dir.expanduser() if home_dir is not None else None
        return RuntimeHomePlan(
            client_name=client_name,
            content_source=manual_home,
            auth_source=manual_home,
            hook_trust_source=manual_home,
            child_home=manual_home,
            descriptor_home=manual_home,
            template_provenance=None,
            mode=RuntimeHomeMode.PROXY_ONLY,
        )

    native_home = resolve_source_home_dir(client_name, home_dir=None, env=env)
    manual_home = home_dir.expanduser() if home_dir is not None else None
    if manual_home is not None:
        content_source = manual_home
        mode = RuntimeHomeMode.MANUAL
        provenance = None
    elif runtime_template is not None:
        validated_template = _validated_template(client_name, runtime_template)
        assert validated_template is not None
        content_source = validated_template.template_home.expanduser()
        mode = RuntimeHomeMode.TEMPLATE
        provenance = RuntimeTemplateProvenance(
            template_id=validated_template.template_id,
            template_home=content_source,
            provenance=validated_template.provenance,
        )
    else:
        content_source = native_home
        mode = RuntimeHomeMode.NATIVE
        provenance = None

    should_overlay = use_runtime_overlay or mode == RuntimeHomeMode.TEMPLATE
    child_home = _runtime_child_home(
        client_name,
        runtime_home_root=runtime_home_root,
        fallback_home=manual_home,
        should_overlay=should_overlay,
    )
    descriptor_home = child_home if mode == RuntimeHomeMode.TEMPLATE else manual_home
    if mode == RuntimeHomeMode.MANUAL and should_overlay and client_name == CLIENT_NAME_CODEX:
        descriptor_home = child_home
    auth_source = native_home if should_overlay or manual_home is not None else content_source
    return RuntimeHomePlan(
        client_name=client_name,
        content_source=content_source,
        auth_source=auth_source,
        hook_trust_source=content_source,
        child_home=child_home,
        descriptor_home=descriptor_home,
        template_provenance=provenance,
        mode=mode,
    )


def prepare_runtime_home(
    plan: RuntimeHomePlan,
    *,
    working_dir: Path,
    env: Mapping[str, str],
) -> RuntimeHomeOverlay | None:
    """Materialize a runtime overlay when the plan has a distinct child home."""
    if plan.runtime_home_dir is None or plan.content_source is None:
        return None
    if plan.mode == RuntimeHomeMode.TEMPLATE:
        return prepare_runtime_home_template_overlay(
            plan.client_name,
            source_home_dir=plan.content_source,
            runtime_home_dir=plan.runtime_home_dir,
            working_dir=working_dir,
            env=env,
            auth_source_home_dir=plan.auth_source,
        )
    return prepare_runtime_home_overlay(
        plan.client_name,
        source_home_dir=plan.content_source,
        runtime_home_dir=plan.runtime_home_dir,
        working_dir=working_dir,
        env=env,
        auth_source_home_dir=plan.auth_source,
        extra_local_names=_template_local_names(plan),
    )


def seed_direct_home_if_needed(
    plan: RuntimeHomePlan,
    *,
    working_dir: Path,
    env: Mapping[str, str] | None = None,
) -> None:
    """Seed non-overlay manual homes through the shared runtime-home seam."""
    if plan.mode != RuntimeHomeMode.MANUAL:
        return
    if plan.runtime_home_dir is not None or plan.child_home is None:
        return
    from transport_matters.cli.home_seed import seed_home_dir

    seed_home_dir(
        plan.client_name,
        home_dir=plan.child_home,
        working_dir=working_dir,
        env=env,
    )


def _validated_template(
    client_name: str, runtime_template: RuntimeTemplateRef | None
) -> RuntimeTemplateRef | None:
    if runtime_template is None:
        return None
    if runtime_template.client_name != client_name:
        raise ValueError(
            f"runtime template client {runtime_template.client_name!r} does not match {client_name!r}"
        )
    validate_runtime_home_template(client_name, runtime_template.template_home)
    return runtime_template


def _runtime_child_home(
    client_name: str,
    *,
    runtime_home_root: Path | None,
    fallback_home: Path | None,
    should_overlay: bool,
) -> Path | None:
    if should_overlay:
        if runtime_home_root is None:
            raise ValueError("runtime_home_root is required when a runtime overlay is active")
        return runtime_home_root / client_name
    return fallback_home


def _template_local_names(plan: RuntimeHomePlan) -> frozenset[str]:
    if plan.mode != RuntimeHomeMode.TEMPLATE:
        return frozenset()
    if plan.client_name == CLIENT_NAME_CLAUDE:
        return frozenset({"projects"})
    if plan.client_name == CLIENT_NAME_CODEX:
        return frozenset({"sessions"})
    raise ValueError(f"unmapped managed client home seeder: {plan.client_name!r}")
