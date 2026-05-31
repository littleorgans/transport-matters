"""Implementation of the `transport-matters claude` command."""

from __future__ import annotations

import shutil
from importlib.resources import as_file
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import typer

from .identity import CLI_COMMAND
from .launch_runtime import (
    CLIENT_NAME_CLAUDE,
    build_launch_env,
    build_managed_child_env,
    build_mitmdump_argv,
    prepare_launch,
    print_invocation,
    reject_passthrough_without_client,
    run_with_workspace_manifest,
)
from .net import loopback_http_url
from .runner import ManagedClient

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from importlib.abc import Traversable


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
        "Upstream must be a valid URL with scheme and host, e.g.\n"
        "  https://api.anthropic.com",
        err=True,
    )
    raise typer.Exit(2)


def _build_start_invocation(
    *,
    addon_path: Path,
    mitmdump: str,
    upstream: str,
    working_dir: Path,
    resolved_storage: Path,
    run_id: str,
    home_dir: Path | None,
    claude_path: str | None,
    claude_passthrough_user: Sequence[str],
    no_claude: bool,
    no_system_prompt: bool,
    debug: bool,
    inject_system_prompt: Callable[..., list[str]],
    user_supplied_system_prompt: Callable[[list[str]], bool],
) -> Callable[[int, int], tuple[list[str], dict[str, str], ManagedClient | None]]:
    """Build the retry-safe invocation factory for `transport-matters claude`."""

    def build_invocation(
        proxy_port: int,
        web_port: int,
    ) -> tuple[list[str], dict[str, str], ManagedClient | None]:
        passthrough = list(claude_passthrough_user)
        if (
            not no_claude
            and not no_system_prompt
            and not user_supplied_system_prompt(passthrough)
        ):
            passthrough = inject_system_prompt(
                passthrough,
                proxy_port=proxy_port,
                web_port=web_port,
            )

        env = build_launch_env(
            working_dir=working_dir,
            storage_dir=resolved_storage,
            proxy_port=proxy_port,
            web_port=web_port,
            run_id=run_id,
        )
        argv = build_mitmdump_argv(
            mitmdump=mitmdump,
            mode=f"reverse:{upstream}",
            proxy_port=proxy_port,
            addon_path=addon_path,
            debug=debug,
        )

        client = None
        if claude_path is not None:
            client_env = build_managed_child_env(
                env,
                client_name=CLIENT_NAME_CLAUDE,
                home_dir=home_dir,
                extra_env={"ANTHROPIC_BASE_URL": loopback_http_url(proxy_port)},
            )
            client = ManagedClient(
                name=CLIENT_NAME_CLAUDE,
                display_name="Claude",
                argv=[claude_path, *passthrough],
                env=client_env,
                cwd=working_dir,
            )
        return argv, env, client

    return build_invocation


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

    with as_file(prepared.addon_traversable) as addon_path:
        build_invocation = _build_start_invocation(
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
            inject_system_prompt=inject_system_prompt,
            user_supplied_system_prompt=user_supplied_system_prompt,
        )

        if print_command:
            print_invocation(
                build_invocation=build_invocation,
                proxy_port=prepared.proxy_port,
                web_port=prepared.web_port,
            )

        def run_launch(write_manifest_for: Callable[[int, int], None]) -> None:
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
