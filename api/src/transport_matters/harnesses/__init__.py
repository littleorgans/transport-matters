"""Static descriptors for executable agent harnesses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class HarnessProxyMode(StrEnum):
    """How mitmproxy is placed between the client and upstream service."""

    REVERSE = "reverse"
    EXPLICIT = "explicit"


class HarnessTrustRequirement(StrEnum):
    """Trust material the managed child needs to use Transport Matters."""

    NONE = "none"
    CODEX_CA_CERTIFICATE = "codex_ca_certificate"


class HarnessShellEnvironmentPolicy(StrEnum):
    """Managed child environment policy applied before process launch."""

    SANITIZED_BASE_URL = "sanitized_base_url"
    SANITIZED_PROXY_WITH_SHELL_EXCLUDES = "sanitized_proxy_with_shell_excludes"


class HarnessPassThroughPolicy(StrEnum):
    """How user supplied arguments reach the executable client."""

    VERBATIM_AFTER_SEPARATOR = "verbatim_after_separator"


class HarnessCapabilities(BaseModel):
    """Feature flags exposed to desktop and web client selection."""

    model_config = ConfigDict(frozen=True)

    startup_probe: bool
    disposable_probe: bool
    overlay_before_work: bool
    tool_schema_overlay: bool
    provider_extras_controls: bool
    replay: bool
    fork: bool
    transport_diagnostics: bool
    codex_turn_telemetry: bool
    websocket_artifacts: bool
    http_fallback_artifacts: bool


@dataclass(frozen=True)
class HarnessDescriptor:
    """Static launch boundary for one executable agent harness."""

    id: str
    display_name: str
    command_name: str
    subcommand_id: str
    binary_option: str
    disable_flag: str
    proxy_mode: HarnessProxyMode
    trust_requirement: HarnessTrustRequirement
    shell_environment_policy: HarnessShellEnvironmentPolicy
    pass_through_policy: HarnessPassThroughPolicy
    capabilities: HarnessCapabilities


class UnsupportedHarnessError(Exception):
    """Raised when no executable harness descriptor is registered."""

    def __init__(self, detail: str = "No harness descriptor registered") -> None:
        self.detail = detail
        super().__init__(detail)


_CLAUDE_DESCRIPTOR = HarnessDescriptor(
    id="claude",
    display_name="Claude Code",
    command_name="claude",
    subcommand_id="claude",
    binary_option="--claude-bin",
    disable_flag="--no-claude",
    proxy_mode=HarnessProxyMode.REVERSE,
    trust_requirement=HarnessTrustRequirement.NONE,
    shell_environment_policy=HarnessShellEnvironmentPolicy.SANITIZED_BASE_URL,
    pass_through_policy=HarnessPassThroughPolicy.VERBATIM_AFTER_SEPARATOR,
    capabilities=HarnessCapabilities(
        startup_probe=False,
        disposable_probe=False,
        overlay_before_work=False,
        tool_schema_overlay=True,
        provider_extras_controls=True,
        replay=False,
        fork=False,
        transport_diagnostics=False,
        codex_turn_telemetry=False,
        websocket_artifacts=False,
        http_fallback_artifacts=False,
    ),
)

_CODEX_DESCRIPTOR = HarnessDescriptor(
    id="codex",
    display_name="Codex",
    command_name="codex",
    subcommand_id="codex",
    binary_option="--codex-bin",
    disable_flag="--no-codex",
    proxy_mode=HarnessProxyMode.EXPLICIT,
    trust_requirement=HarnessTrustRequirement.CODEX_CA_CERTIFICATE,
    shell_environment_policy=HarnessShellEnvironmentPolicy.SANITIZED_PROXY_WITH_SHELL_EXCLUDES,
    pass_through_policy=HarnessPassThroughPolicy.VERBATIM_AFTER_SEPARATOR,
    capabilities=HarnessCapabilities(
        startup_probe=False,
        disposable_probe=False,
        overlay_before_work=False,
        tool_schema_overlay=True,
        provider_extras_controls=True,
        replay=False,
        fork=False,
        transport_diagnostics=True,
        codex_turn_telemetry=True,
        websocket_artifacts=True,
        http_fallback_artifacts=True,
    ),
)

_DESCRIPTORS = (_CLAUDE_DESCRIPTOR, _CODEX_DESCRIPTOR)
_DESCRIPTORS_BY_ID = {descriptor.id: descriptor for descriptor in _DESCRIPTORS}


def list_harness_descriptors() -> tuple[HarnessDescriptor, ...]:
    """Return the supported executable harness descriptors."""
    return _DESCRIPTORS


def get_harness_descriptor(harness_id: str) -> HarnessDescriptor:
    """Return the descriptor registered for an executable harness id."""
    try:
        return _DESCRIPTORS_BY_ID[harness_id]
    except KeyError as exc:
        raise UnsupportedHarnessError(
            detail=f"No harness registered for {harness_id}"
        ) from exc


__all__ = [
    "HarnessCapabilities",
    "HarnessDescriptor",
    "HarnessPassThroughPolicy",
    "HarnessProxyMode",
    "HarnessShellEnvironmentPolicy",
    "HarnessTrustRequirement",
    "UnsupportedHarnessError",
    "get_harness_descriptor",
    "list_harness_descriptors",
]
