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
    build_launch_env,
    new_run_id,
    reject_passthrough_without_client,
    resolve_launch_ports,
    resolve_mitmdump_or_exit,
    resolve_storage_dir,
    resolve_working_dir,
    run_with_workspace_manifest,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from importlib.abc import Traversable


def _resolve_claude_path(
    *,
    claude_bin: Path | None,
    no_claude: bool,
    which: Callable[[str], str | None],
) -> str | None:
    """Resolve the Claude binary or exit with an actionable hint."""
    if no_claude:
        return None

    claude_path = str(claude_bin) if claude_bin is not None else which("claude")
    if claude_path is not None:
        return claude_path

    typer.secho(
        "error: `claude` was not found on PATH.",
        fg=typer.colors.RED,
        err=True,
    )
    typer.echo(
        "Install Claude Code, or point at an existing install:\n"
        "  npm install -g @anthropic-ai/claude-code\n"
        "  # or\n"
        f"  {CLI_COMMAND} claude --claude-bin /path/to/claude\n"
        "  # or run proxy-only:\n"
        f"  {CLI_COMMAND} claude --no-claude",
        err=True,
    )
    raise typer.Exit(2)


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
    claude_path: str | None,
    claude_passthrough_user: list[str],
    no_claude: bool,
    no_system_prompt: bool,
    debug: bool,
    inject_system_prompt: Callable[..., list[str]],
    user_supplied_system_prompt: Callable[[list[str]], bool],
) -> Callable[[int, int], tuple[list[str], dict[str, str], list[str] | None]]:
    """Build the retry-safe invocation factory for `transport-matters claude`."""

    def build_invocation(
        proxy_port: int,
        web_port: int,
    ) -> tuple[list[str], dict[str, str], list[str] | None]:
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
        argv = [
            mitmdump,
            "--mode",
            f"reverse:{upstream}",
            "--listen-host",
            "127.0.0.1",
            "--listen-port",
            str(proxy_port),
            "-s",
            str(addon_path),
        ]
        if not debug:
            argv.extend(["--set", "termlog_verbosity=warn"])

        claude_argv = [claude_path, *passthrough] if claude_path is not None else None
        return argv, env, claude_argv

    return build_invocation


def run_start(
    *,
    directory: Path | None,
    claude_passthrough: list[str],
    proxy_port: int | None,
    web_port: int | None,
    upstream: str,
    storage_dir: Path | None,
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
    run_with_retry: Callable[..., None],
    print_contention_error: Callable[..., None],
) -> None:
    """Execute the `claude` launch lifecycle."""
    reject_passthrough_without_client(
        disabled=no_claude,
        passthrough=claude_passthrough,
        flag="--no-claude",
    )

    addon_traversable = require_addon()
    mitmdump = resolve_mitmdump_or_exit(resolve_mitmdump=resolve_mitmdump)
    claude_path = _resolve_claude_path(
        claude_bin=claude_bin,
        no_claude=no_claude,
        which=which,
    )
    _validate_upstream(upstream)

    working_dir = resolve_working_dir(directory)
    proxy_port, web_port, proxy_user_supplied, web_user_supplied = resolve_launch_ports(
        proxy_port=proxy_port,
        web_port=web_port,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
    )
    resolved_storage = resolve_storage_dir(
        storage_dir=storage_dir,
        working_dir=working_dir,
    )
    run_id = new_run_id()
    claude_passthrough_user = list(claude_passthrough)

    with as_file(addon_traversable) as addon_path:
        build_invocation = _build_start_invocation(
            addon_path=addon_path,
            mitmdump=mitmdump,
            upstream=upstream,
            working_dir=working_dir,
            resolved_storage=resolved_storage,
            run_id=run_id,
            claude_path=claude_path,
            claude_passthrough_user=claude_passthrough_user,
            no_claude=no_claude,
            no_system_prompt=no_system_prompt,
            debug=debug,
            inject_system_prompt=inject_system_prompt,
            user_supplied_system_prompt=user_supplied_system_prompt,
        )

        if print_command:
            mitmdump_argv, _env, claude_argv = build_invocation(proxy_port, web_port)
            typer.echo(" ".join(mitmdump_argv))
            if claude_argv is not None:
                typer.echo(" ".join(claude_argv))
            raise typer.Exit(0)

        def run_launch(write_manifest_for: Callable[[int, int], None]) -> None:
            def print_banner_for(proxy_port: int, web_port: int) -> None:
                print_banner(
                    proxy_port=proxy_port,
                    web_port=web_port,
                    upstream=upstream,
                    working_dir=working_dir,
                    no_claude=no_claude,
                )

            run_with_retry(
                proxy_port=proxy_port,
                web_port=web_port,
                proxy_user_supplied=proxy_user_supplied,
                web_user_supplied=web_user_supplied,
                build_invocation=build_invocation,
                print_banner_for=print_banner_for,
                write_manifest_for=write_manifest_for,
                resolved_storage=resolved_storage,
                working_dir=working_dir,
            )

        run_with_workspace_manifest(
            working_dir=working_dir,
            storage_dir=resolved_storage,
            run_id=run_id,
            on_locked=print_contention_error,
            run_launch=run_launch,
        )
