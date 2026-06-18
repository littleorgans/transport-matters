"""Implementation for the `transport-matters claude` launch command."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import typer

from .launch_runtime import preflight_session_store_or_exit, reject_passthrough_without_client

if TYPE_CHECKING:
    from collections.abc import Callable
    from importlib.resources.abc import Traversable
    from pathlib import Path


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
    default_client_passthrough: tuple[str, ...] = (),
) -> None:
    """Execute the `claude` launch lifecycle."""
    from transport_matters.captured_run import CapturedRunRequest, run_captured_run_on_local_tty

    reject_passthrough_without_client(
        disabled=no_claude,
        passthrough=claude_passthrough,
        flag="--no-claude",
    )

    # Hard-block the launch if the session store is unconfigured/unreachable, so the
    # canvas never opens against a dead store. A dry --print-command run is exempt.
    if not print_command:
        preflight_session_store_or_exit()

    run_captured_run_on_local_tty(
        CapturedRunRequest(
            harness="claude",
            passthrough=tuple(claude_passthrough),
            directory=directory,
            proxy_port=proxy_port,
            web_port=web_port,
            upstream=upstream,
            storage_dir=storage_dir,
            home_dir=home_dir,
            client_bin=claude_bin,
            client_disabled=no_claude,
            no_system_prompt=no_system_prompt,
            debug=debug,
            default_client_passthrough=default_client_passthrough,
        ),
        print_command=print_command,
        require_addon=require_addon,
        resolve_mitmdump=resolve_mitmdump,
        which=which,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
        inject_system_prompt=inject_system_prompt,
        user_supplied_system_prompt=user_supplied_system_prompt,
        validate_after_client_resolution=lambda: _validate_upstream(upstream),
        print_banner=print_banner,
        run_client_with_retry=run_client_with_retry,
    )
