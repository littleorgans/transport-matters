"""Shared setup context for captured-run orchestration."""

from __future__ import annotations

import shutil
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import datetime
from importlib.resources import as_file
from typing import TYPE_CHECKING

from transport_matters.captured_claude import build_claude_captured_invocation
from transport_matters.captured_run_models import (
    CLAUDE_CLIENT_NAME,
    CODEX_CLIENT_NAME,
    WEB_RUNTIME_EMBEDDED,
    WEB_RUNTIME_EXTERNAL,
    CapturedRunRequest,
)
from transport_matters.launch_manifest import write_workspace_manifest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from importlib.resources.abc import Traversable
    from pathlib import Path

    from transport_matters.cli.launch_profile import LaunchProfile, ManagedSession
    from transport_matters.cli.launch_runtime import LaunchPreparation
    from transport_matters.cli.runner import ManagedClient
    from transport_matters.lock import WorkspaceLock


@dataclass(slots=True)
class CapturedRunContext:
    request: CapturedRunRequest
    profile: LaunchProfile
    prepared: LaunchPreparation
    managed_session: ManagedSession | None
    build_invocation: Callable[
        [int, int | None],
        tuple[list[str], dict[str, str], ManagedClient | None],
    ]
    resource_stack: ExitStack
    runtime_home_dir: Path | None = None


def build_captured_run_context(
    request: CapturedRunRequest,
    *,
    profile: LaunchProfile | None,
    require_addon: Callable[[], Traversable],
    resolve_mitmdump: Callable[[], str | None],
    which: Callable[[str], str | None],
    port_in_use: Callable[[int], bool],
    allocate_port_pair: Callable[[], tuple[int, int]],
    inject_system_prompt: Callable[..., list[str]],
    user_supplied_system_prompt: Callable[[list[str]], bool],
    validate_after_client_resolution: Callable[[], None] | None,
    env: Mapping[str, str],
    now: datetime | None,
    write: bool,
) -> CapturedRunContext:
    """Resolve launch state and build the provider specific invocation factory."""
    from transport_matters.cli.launch_profile import PROFILES, prepare_managed_session
    from transport_matters.cli.launch_runtime import prepare_launch

    try:
        launch_profile = profile or PROFILES[request.client_name]
    except KeyError as exc:
        raise ValueError(f"unsupported captured client: {request.client_name!r}") from exc
    if request.web_runtime == WEB_RUNTIME_EXTERNAL and request.web_port is not None:
        raise ValueError("external captured run must not include a web port")
    prepared = prepare_launch(
        passthrough=list(request.passthrough),
        directory=request.directory,
        proxy_port=request.proxy_port,
        web_port=request.web_port,
        storage_dir=request.storage_dir,
        client_name=request.client_name,
        bin_override=request.client_bin,
        client_disabled=request.client_disabled,
        not_found_hint=_client_not_found_hint(request.client_name),
        require_addon=require_addon,
        resolve_mitmdump=resolve_mitmdump,
        which=which,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
        validate_after_client_resolution=validate_after_client_resolution,
        web_required=request.web_runtime == WEB_RUNTIME_EMBEDDED,
    )
    stack = ExitStack()
    effective_request = request
    runtime_home_dir = None
    try:
        if write and prepared.client_path is not None:
            from transport_matters.cli.home_seed import (
                prepare_runtime_home_overlay,
                resolve_source_home_dir,
            )

            source_home_dir = resolve_source_home_dir(
                request.client_name,
                home_dir=request.home_dir,
                env=env,
            )
            runtime_home_root = prepared.resolved_storage / "runtime-home"
            runtime_home_dir = runtime_home_root / request.client_name
            prepare_runtime_home_overlay(
                request.client_name,
                source_home_dir=source_home_dir,
                runtime_home_dir=runtime_home_dir,
                working_dir=prepared.working_dir,
                env=env,
            )
            stack.callback(shutil.rmtree, runtime_home_root, ignore_errors=True)
            effective_request = replace(request, home_dir=source_home_dir)

        managed_session = prepare_managed_session(
            launch_profile,
            client_path=prepared.client_path,
            passthrough=prepared.passthrough_user,
            working_dir=prepared.working_dir,
            home_dir=effective_request.home_dir,
            env=env,
            now=now or datetime.now().astimezone(),
            write=write,
        )
        addon_path = stack.enter_context(as_file(prepared.addon_traversable))
        if request.client_name == CLAUDE_CLIENT_NAME:
            build_invocation = build_claude_captured_invocation(
                addon_path=addon_path,
                mitmdump=prepared.mitmdump,
                upstream=request.upstream,
                working_dir=prepared.working_dir,
                resolved_storage=prepared.resolved_storage,
                run_id=prepared.run_id,
                home_dir=effective_request.home_dir,
                runtime_home_dir=runtime_home_dir,
                claude_path=prepared.client_path,
                claude_passthrough_user=prepared.passthrough_user,
                no_claude=request.client_disabled,
                no_system_prompt=request.no_system_prompt,
                debug=request.debug,
                profile=launch_profile,
                managed_session=managed_session,
                inject_system_prompt=inject_system_prompt,
                user_supplied_system_prompt=user_supplied_system_prompt,
                web_runtime=request.web_runtime,
                default_client_passthrough=request.default_client_passthrough,
            )
        else:
            from transport_matters.captured_codex import build_codex_captured_invocation

            build_invocation = build_codex_captured_invocation(
                resource_stack=stack,
                addon_path=addon_path,
                mitmdump=prepared.mitmdump,
                working_dir=prepared.working_dir,
                resolved_storage=prepared.resolved_storage,
                run_id=prepared.run_id,
                home_dir=effective_request.home_dir,
                runtime_home_dir=runtime_home_dir,
                codex_path=prepared.client_path,
                codex_passthrough_user=prepared.passthrough_user,
                debug=request.debug,
                profile=launch_profile,
                managed_session=managed_session,
                env=env,
                web_runtime=request.web_runtime,
                default_client_passthrough=request.default_client_passthrough,
            )
    except Exception:
        stack.close()
        raise
    return CapturedRunContext(
        request=effective_request,
        profile=launch_profile,
        prepared=prepared,
        managed_session=managed_session,
        build_invocation=build_invocation,
        resource_stack=stack,
        runtime_home_dir=runtime_home_dir,
    )


def persist_owned_session_facts(ctx: CapturedRunContext) -> None:
    """Persist launch-owned session facts for managed sessions."""
    from transport_matters.cli.launch_profile import persist_owned_session_facts

    if ctx.managed_session is None:
        return
    persist_owned_session_facts(
        ctx.profile,
        ctx.managed_session,
        run_id=ctx.prepared.run_id,
        storage_root=ctx.prepared.resolved_storage,
        home_dir=ctx.request.home_dir,
    )


def write_captured_run_manifest(
    ctx: CapturedRunContext,
    workspace_lock: WorkspaceLock,
    *,
    proxy_port: int,
    web_port: int | None,
) -> None:
    """Write the manifest for the active captured run attempt."""
    write_workspace_manifest(
        manifest_path=workspace_lock.manifest_path,
        working_dir=ctx.prepared.working_dir,
        storage_dir=ctx.prepared.resolved_storage,
        run_id=ctx.prepared.run_id,
        home_dir=ctx.request.home_dir,
        proxy_port=proxy_port,
        web_port=web_port,
    )


def _client_not_found_hint(client_name: str) -> str:
    if client_name == CODEX_CLIENT_NAME:
        from transport_matters.cli.identity import CLI_COMMAND

        return (
            "Install Codex, or point at an existing binary:\n"
            f"  {CLI_COMMAND} codex --codex-bin /path/to/codex"
        )
    return _claude_not_found_hint()


def _claude_not_found_hint() -> str:
    from transport_matters.cli.identity import CLI_COMMAND

    return (
        "Install Claude Code, or point at an existing install:\n"
        "  npm install -g @anthropic-ai/claude-code\n"
        "  # or\n"
        f"  {CLI_COMMAND} claude --claude-bin /path/to/claude\n"
        "  # or run proxy-only:\n"
        f"  {CLI_COMMAND} claude --no-claude"
    )
