"""Implementation of the `transport-matters claude` command."""

import os
import shutil
from datetime import datetime
from importlib.resources import as_file
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import typer

from transport_matters.captured_run import build_start_invocation

from .home_seed import seed_home_dir
from .identity import CLI_COMMAND
from .launch_profile import (
    ClaudeLaunchProfile,
    persist_owned_session_facts,
    prepare_managed_session,
)
from .launch_runtime import (
    CLIENT_NAME_CLAUDE,
    preflight_session_store_or_exit,
    prepare_launch,
    print_invocation,
    reject_passthrough_without_client,
    run_with_workspace_manifest,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from importlib.resources.abc import Traversable


def _validate_upstream(upstream: str) -> None:
    """Validate the reverse proxy upstream URL."""
    parsed_url = urlparse(upstream)
    if parsed_url.scheme and parsed_url.hostname:
        return

    typer.secho(
        f"error: invalid upstream URL: {upstream!r}",
        fg=typer.colors.RED,
        err=True,
    )
    typer.echo(
        "Upstream must be a valid URL with scheme and host, e.g.\n  https://api.anthropic.com",
        err=True,
    )
    raise typer.Exit(2)


def run_start(
    *,
    directory: Path | None,
    claude_passthrough: list[str],
    proxy_port: int | None,
    web_port: int | None,
    upstream: str,
    storage_dir: Path | None,
    home_dir: Path | None,
    claude_bin: Path | None,
    no_claude: bool,
    no_system_prompt: bool,
    debug: bool,
    print_command: bool,
    require_addon: Callable[[], Traversable],
    resolve_mitmdump: Callable[[], str | None],
    which: Callable[[str], str | None] = shutil.which,
    port_in_use: Callable[[int], bool],
    allocate_port_pair: Callable[[], tuple[int, int]],
    inject_system_prompt: Callable[..., list[str]],
    user_supplied_system_prompt: Callable[[list[str]], bool],
    print_banner: Callable[..., None],
    run_client_with_retry: Callable[..., None],
) -> None:
    """Execute the `claude` launch lifecycle."""
    reject_passthrough_without_client(
        disabled=no_claude,
        passthrough=claude_passthrough,
        flag="--no-claude",
    )

    # Hard-block the launch if the session store is unconfigured/unreachable, so the
    # canvas never opens against a dead store (a dry --print-command run is exempt).
    if not print_command:
        preflight_session_store_or_exit()

    prepared = prepare_launch(
        passthrough=claude_passthrough,
        directory=directory,
        proxy_port=proxy_port,
        web_port=web_port,
        storage_dir=storage_dir,
        client_name=CLIENT_NAME_CLAUDE,
        bin_override=claude_bin,
        client_disabled=no_claude,
        not_found_hint=(
            "Install Claude Code, or point at an existing install:\n"
            "  npm install -g @anthropic-ai/claude-code\n"
            "  # or\n"
            f"  {CLI_COMMAND} claude --claude-bin /path/to/claude\n"
            "  # or run proxy-only:\n"
            f"  {CLI_COMMAND} claude --no-claude"
        ),
        require_addon=require_addon,
        resolve_mitmdump=resolve_mitmdump,
        which=which,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
        validate_after_client_resolution=lambda: _validate_upstream(upstream),
    )

    # Managed-mint (§5.2c): mint the owned uuid + compute the deterministic transcript descriptor ONCE,
    # before the retry loop, so every attempt injects the same `--session-id`. ``write`` is gated on
    # print-command (dry run touches no disk); claude needs no seed, so this only computes the
    # descriptor. ``None`` when proxy-only or the user pinned a session (honor passthrough).
    profile = ClaudeLaunchProfile()
    managed_session = prepare_managed_session(
        profile,
        client_path=prepared.client_path,
        passthrough=prepared.passthrough_user,
        working_dir=prepared.working_dir,
        home_dir=home_dir,
        env=os.environ,
        now=datetime.now().astimezone(),
        write=not print_command,
    )

    with as_file(prepared.addon_traversable) as addon_path:
        build_invocation = build_start_invocation(
            addon_path=addon_path,
            mitmdump=prepared.mitmdump,
            upstream=upstream,
            working_dir=prepared.working_dir,
            resolved_storage=prepared.resolved_storage,
            run_id=prepared.run_id,
            home_dir=home_dir,
            claude_path=prepared.client_path,
            claude_passthrough_user=prepared.passthrough_user,
            no_claude=no_claude,
            no_system_prompt=no_system_prompt,
            debug=debug,
            profile=profile,
            managed_session=managed_session,
            inject_system_prompt=inject_system_prompt,
            user_supplied_system_prompt=user_supplied_system_prompt,
        )

        if print_command:
            print_invocation(
                build_invocation=build_invocation,
                proxy_port=prepared.proxy_port,
                web_port=prepared.web_port,
            )
        if not print_command and home_dir is not None and prepared.client_path is not None:
            seed_home_dir(
                CLIENT_NAME_CLAUDE,
                home_dir=home_dir,
                working_dir=prepared.working_dir,
            )

        def run_launch(write_manifest_for: Callable[[int, int], None]) -> None:
            # Durable owned-launch facts (§11.1): written once here, inside the per-run lock (the run
            # dir exists) and before the retry loop, so a §10.5 rebuild reads the owned state without
            # the live env. ``None`` for proxy-only / user-pinned sessions (nothing owned to persist).
            if managed_session is not None:
                persist_owned_session_facts(
                    profile,
                    managed_session,
                    run_id=prepared.run_id,
                    storage_root=prepared.resolved_storage,
                    home_dir=home_dir,
                )

            def print_banner_for(proxy_port: int, web_port: int) -> None:
                print_banner(
                    proxy_port=proxy_port,
                    web_port=web_port,
                    upstream=upstream,
                    working_dir=prepared.working_dir,
                    no_claude=no_claude,
                )

            run_client_with_retry(
                proxy_port=prepared.proxy_port,
                web_port=prepared.web_port,
                proxy_user_supplied=prepared.proxy_user_supplied,
                web_user_supplied=prepared.web_user_supplied,
                build_invocation=build_invocation,
                print_banner_for=print_banner_for,
                write_manifest_for=write_manifest_for,
                resolved_storage=prepared.resolved_storage,
            )

        run_with_workspace_manifest(
            working_dir=prepared.working_dir,
            storage_dir=prepared.resolved_storage,
            run_id=prepared.run_id,
            home_dir=home_dir,
            run_launch=run_launch,
        )
