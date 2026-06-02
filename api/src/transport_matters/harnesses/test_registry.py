import pytest

from transport_matters.adapters import get_adapter_for_provider
from transport_matters.exceptions import UnsupportedProviderError
from transport_matters.harnesses import (
    HarnessPassThroughPolicy,
    HarnessProxyMode,
    HarnessShellEnvironmentPolicy,
    HarnessTrustRequirement,
    UnsupportedHarnessError,
    get_harness_descriptor,
    list_harness_descriptors,
)


def test_registry_lists_only_current_harnesses() -> None:
    descriptors = list_harness_descriptors()

    assert tuple(descriptor.id for descriptor in descriptors) == ("claude", "codex")
    assert {descriptor.command_name for descriptor in descriptors} == {
        "claude",
        "codex",
    }


def test_registry_resolves_descriptor_by_id() -> None:
    claude = get_harness_descriptor("claude")

    assert claude is get_harness_descriptor("claude")
    assert claude.display_name == "Claude Code"


def test_registry_rejects_unknown_harness() -> None:
    with pytest.raises(UnsupportedHarnessError) as exc_info:
        get_harness_descriptor("gemini")

    assert "No harness registered for gemini" in str(exc_info.value)


def test_claude_descriptor_matches_current_launch_boundary() -> None:
    claude = get_harness_descriptor("claude")

    assert claude.subcommand_id == "claude"
    assert claude.command_name == "claude"
    assert claude.binary_option == "--claude-bin"
    assert claude.disable_flag == "--no-claude"
    assert claude.proxy_mode is HarnessProxyMode.REVERSE
    assert claude.trust_requirement is HarnessTrustRequirement.NONE
    assert claude.shell_environment_policy is HarnessShellEnvironmentPolicy.SANITIZED_BASE_URL
    assert claude.pass_through_policy is HarnessPassThroughPolicy.VERBATIM_AFTER_SEPARATOR
    assert claude.capabilities.startup_probe is False
    assert claude.capabilities.disposable_probe is False
    assert claude.capabilities.overlay_before_work is False
    assert claude.capabilities.tool_schema_overlay is True
    assert claude.capabilities.provider_extras_controls is True
    assert claude.capabilities.replay is False
    assert claude.capabilities.fork is False
    assert claude.capabilities.transport_diagnostics is False
    assert claude.capabilities.codex_turn_telemetry is False
    assert claude.capabilities.websocket_artifacts is False
    assert claude.capabilities.http_fallback_artifacts is False


def test_codex_descriptor_matches_current_launch_boundary() -> None:
    codex = get_harness_descriptor("codex")

    assert codex.subcommand_id == "codex"
    assert codex.command_name == "codex"
    assert codex.binary_option == "--codex-bin"
    assert codex.disable_flag == "--no-codex"
    assert codex.proxy_mode is HarnessProxyMode.EXPLICIT
    assert codex.trust_requirement is HarnessTrustRequirement.CODEX_CA_CERTIFICATE
    assert (
        codex.shell_environment_policy
        is HarnessShellEnvironmentPolicy.SANITIZED_PROXY_WITH_SHELL_EXCLUDES
    )
    assert codex.pass_through_policy is HarnessPassThroughPolicy.VERBATIM_AFTER_SEPARATOR
    assert codex.capabilities.startup_probe is False
    assert codex.capabilities.disposable_probe is False
    assert codex.capabilities.overlay_before_work is False
    assert codex.capabilities.tool_schema_overlay is True
    assert codex.capabilities.provider_extras_controls is True
    assert codex.capabilities.replay is False
    assert codex.capabilities.fork is False
    assert codex.capabilities.transport_diagnostics is True
    assert codex.capabilities.codex_turn_telemetry is True
    assert codex.capabilities.websocket_artifacts is True
    assert codex.capabilities.http_fallback_artifacts is True


def test_harness_registry_does_not_replace_provider_lookup() -> None:
    assert get_harness_descriptor("claude").id == "claude"
    with pytest.raises(UnsupportedProviderError):
        get_adapter_for_provider("claude")

    assert get_adapter_for_provider("codex").name == "codex"
