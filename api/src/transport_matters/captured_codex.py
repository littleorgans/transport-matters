"""Captured Codex launch helpers shared by pane and CLI seams."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from contextlib import ExitStack
    from pathlib import Path

    from transport_matters.cli.launch_profile import LaunchProfile, ManagedSession
    from transport_matters.cli.runner import ManagedClient


def build_codex_captured_invocation(
    *,
    resource_stack: ExitStack,
    addon_path: Path,
    mitmdump: str,
    working_dir: Path,
    resolved_storage: Path,
    run_id: str,
    home_dir: Path | None,
    codex_path: str | None,
    codex_passthrough_user: Sequence[str],
    debug: bool,
    profile: LaunchProfile,
    managed_session: ManagedSession | None,
    env: Mapping[str, str],
    web_runtime: str,
    default_client_passthrough: Sequence[str] = (),
    runtime_home_dir: Path | None = None,
) -> Callable[[int, int | None], tuple[list[str], dict[str, str], ManagedClient | None]]:
    """Build a nested capture only Codex invocation through the existing Codex path."""
    from transport_matters.cli.codex_cmd import (
        build_codex_invocation,
        resolve_codex_addons_and_ca,
    )
    from transport_matters.cli.trust import resolve_codex_ca_certificate

    force_http_fallback_addon_path, codex_ca_certificate = resolve_codex_addons_and_ca(
        stack=resource_stack,
        force_http_fallback=False,
        require_force_http_fallback_addon=lambda: addon_path,
        client_path=codex_path,
        print_command=False,
        resolve_codex_ca_certificate=resolve_codex_ca_certificate,
        env=env,
    )
    return build_codex_invocation(
        addon_path=addon_path,
        force_http_fallback_addon_path=force_http_fallback_addon_path,
        mitmdump=mitmdump,
        working_dir=working_dir,
        resolved_storage=resolved_storage,
        run_id=run_id,
        home_dir=home_dir,
        runtime_home_dir=runtime_home_dir,
        codex_path=codex_path,
        codex_passthrough_user=codex_passthrough_user,
        codex_ca_certificate=codex_ca_certificate,
        profile=profile,
        managed_session=managed_session,
        debug=debug,
        web_runtime=web_runtime,
        default_client_passthrough=default_client_passthrough,
    )
