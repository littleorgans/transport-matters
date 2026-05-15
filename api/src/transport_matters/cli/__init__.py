"""Transport Matters command-line interface.

This package is the `[project.scripts]` entry point installed by `pip` /
`uv tool install` / the `install.sh` bootstrap. It exposes two launch
commands (`claude`, `codex`) plus support commands (`doctor`, `paths`,
`list`, `version`).

Module layout:
  help.py         — all static help text + plain-text renderers
  net.py          — port probing helpers
  banner.py       — startup banner
  runner.py       — supervisor-driven child lifecycles
  start_cmd.py    — `transport-matters claude` implementation
  codex_cmd.py    — `transport-matters codex` implementation
  launch_runtime.py — shared launch plumbing
  __init__.py     — typer app, command registration, and re-exports

Re-exports (`SIGNAL_EXIT`, `ProcessSupervisor`, `_port_in_use`,
`_wait_for_port_ready`, `_print_banner`, `_run_children`) stay at
package scope so existing imports and most test monkeypatch paths
remain valid.
"""

from __future__ import annotations

import shutil
import sysconfig
from importlib.resources import files
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from collections.abc import Iterable
    from importlib.abc import Traversable

from transport_matters import __version__
from transport_matters.lock import WorkspaceLock, WorkspaceLocked
from transport_matters.manifest import Manifest
from transport_matters.manifest import write as manifest_write
from transport_matters.supervisor import SIGNAL_EXIT, ProcessSupervisor
from transport_matters.workspace import workspace_id, workspace_root, workspace_storage

from .banner import _print_banner, _print_client_banner
from .codex_cmd import run_codex
from .diagnose import run_doctor
from .help import _PlainCommand, _PlainGroup
from .identity import CLI_COMMAND
from .instances import _list_instances, _print_contention_error
from .net import _port_in_use, _wait_for_port_ready, validate_port_option
from .paths import resolve_paths
from .ports import PortAllocationError, allocate_port_pair
from .prompt import inject_system_prompt, user_supplied_system_prompt
from .runner import BindFailure, _run_children, _run_client_with_retry, _run_with_retry
from .start_cmd import run_start
from .trust import resolve_codex_ca_certificate

__all__ = [
    "SIGNAL_EXIT",
    "BindFailure",
    "Manifest",
    "PortAllocationError",
    "ProcessSupervisor",
    "WorkspaceLock",
    "WorkspaceLocked",
    "_list_instances",
    "_port_in_use",
    "_print_banner",
    "_print_contention_error",
    "_run_children",
    "_run_client_with_retry",
    "_run_with_retry",
    "_wait_for_port_ready",
    "allocate_port_pair",
    "inject_system_prompt",
    "main",
    "manifest_write",
    "user_supplied_system_prompt",
    "workspace_id",
    "workspace_root",
    "workspace_storage",
]


main = typer.Typer(
    name=CLI_COMMAND,
    cls=_PlainGroup,
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _resolve_mitmdump() -> str | None:
    """Prefer the console script from the active Transport Matters environment."""
    scripts_dir = sysconfig.get_path("scripts")
    if scripts_dir:
        resolved = shutil.which("mitmdump", path=scripts_dir)
        if resolved is not None:
            return resolved
    return shutil.which("mitmdump")


def _split_passthrough(
    ctx: typer.Context,
    directory: Path | None,
) -> tuple[Path | None, list[str]]:
    """Split the raw argv into `(directory, pass-through)` for the client."""
    passthrough: list[str] = list(ctx.args)
    if directory is not None and directory.name.startswith("-"):
        passthrough = [directory.name, *passthrough]
        directory = None
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    return directory, passthrough


def _require_addon() -> Traversable:
    """Locate the packaged mitmproxy addon or exit with a repair hint."""
    addon_traversable = files("transport_matters") / "addon.py"
    if not addon_traversable.is_file():
        typer.secho(
            "error: could not locate the Transport Matters mitmproxy addon.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(
            "The package may be corrupted. Try reinstalling:\n"
            f"  uv tool install --force {CLI_COMMAND}",
            err=True,
        )
        raise typer.Exit(2)
    return addon_traversable


def _require_force_http_fallback_addon() -> Traversable:
    """Locate the test-mode Codex HTTP fallback injector addon."""
    addon_traversable = files("transport_matters") / "force_http_fallback_addon.py"
    if not addon_traversable.is_file():
        typer.secho(
            "error: could not locate the --force-http-fallback test addon.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(
            "The package may be corrupted. Try reinstalling:\n"
            f"  uv tool install --force {CLI_COMMAND}",
            err=True,
        )
        raise typer.Exit(2)
    return addon_traversable


def _merge_no_proxy(current: str | None, hosts: Iterable[str]) -> str:
    """Add loopback hosts to `NO_PROXY` without dropping existing entries."""
    merged: list[str] = []
    seen: set[str] = set()
    for raw in [*(current or "").split(","), *hosts]:
        entry = raw.strip()
        if not entry or entry in seen:
            continue
        seen.add(entry)
        merged.append(entry)
    return ",".join(merged)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"{CLI_COMMAND} {__version__}")
        raise typer.Exit()


@main.callback()
def _root(
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show the installed version and exit.",
        ),
    ] = False,
) -> None:
    """Root callback. Handles `--version` without requiring a subcommand."""


@main.command(
    name="claude",
    cls=_PlainCommand,
    no_args_is_help=False,
    context_settings={
        "help_option_names": ["-h", "--help"],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def claude(
    ctx: typer.Context,
    directory: Annotated[
        Path | None,
        typer.Argument(
            help="Working directory for Claude Code (defaults to cwd).",
            show_default=False,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    proxy_port: Annotated[
        int | None,
        typer.Option(
            "--proxy-port",
            "-p",
            envvar="TRANSPORT_MATTERS_PROXY_PORT",
            help=(
                "Port for the reverse-proxy listener "
                "(default: kernel-allocated free port)."
            ),
            show_default=False,
            callback=validate_port_option,
        ),
    ] = None,
    web_port: Annotated[
        int | None,
        typer.Option(
            "--web-port",
            "-w",
            envvar="TRANSPORT_MATTERS_WEB_PORT",
            help=(
                "Port for the embedded web UI (default: kernel-allocated free port)."
            ),
            show_default=False,
            callback=validate_port_option,
        ),
    ] = None,
    upstream: Annotated[
        str,
        typer.Option(
            "--upstream",
            "-u",
            envvar="TRANSPORT_MATTERS_UPSTREAM_URL",
            help="Upstream provider base URL (reverse proxy target).",
        ),
    ] = "https://api.anthropic.com",
    storage_dir: Annotated[
        Path | None,
        typer.Option(
            "--storage-dir",
            "-d",
            envvar="TRANSPORT_MATTERS_STORAGE_DIR",
            help=(
                "Directory for captured exchanges, rules, and the index. "
                "Defaults to `~/.transport-matters`."
            ),
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    claude_bin: Annotated[
        Path | None,
        typer.Option(
            "--claude-bin",
            help="Path to the Claude Code binary (default: `claude` on PATH).",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    no_claude: Annotated[
        bool,
        typer.Option(
            "--no-claude",
            help="Run the proxy only; don't spawn Claude Code.",
        ),
    ] = False,
    no_system_prompt: Annotated[
        bool,
        typer.Option(
            "--no-system-prompt",
            help="Skip the auto-injected Transport Matters system prompt.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable verbose mitmproxy output (for troubleshooting).",
        ),
    ] = False,
    print_command: Annotated[
        bool,
        typer.Option(
            "--print-command",
            help="Print the resolved child invocations and exit without running them.",
        ),
    ] = False,
) -> None:
    """Start the Transport Matters workbench: proxy + Claude Code."""
    directory, claude_passthrough = _split_passthrough(ctx, directory)
    run_start(
        directory=directory,
        claude_passthrough=claude_passthrough,
        proxy_port=proxy_port,
        web_port=web_port,
        upstream=upstream,
        storage_dir=storage_dir,
        claude_bin=claude_bin,
        no_claude=no_claude,
        no_system_prompt=no_system_prompt,
        debug=debug,
        print_command=print_command,
        require_addon=_require_addon,
        resolve_mitmdump=_resolve_mitmdump,
        which=shutil.which,
        port_in_use=_port_in_use,
        allocate_port_pair=allocate_port_pair,
        inject_system_prompt=inject_system_prompt,
        user_supplied_system_prompt=user_supplied_system_prompt,
        print_banner=_print_banner,
        run_client_with_retry=_run_client_with_retry,
        print_contention_error=_print_contention_error,
    )


@main.command(
    cls=_PlainCommand,
    no_args_is_help=False,
    context_settings={
        "help_option_names": ["-h", "--help"],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def codex(
    ctx: typer.Context,
    directory: Annotated[
        Path | None,
        typer.Argument(
            help="Working dir for Codex (defaults to cwd).",
            show_default=False,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    proxy_port: Annotated[
        int | None,
        typer.Option(
            "--proxy-port",
            "-p",
            envvar="TRANSPORT_MATTERS_PROXY_PORT",
            help=(
                "Port for the explicit-proxy listener "
                "(default: kernel-allocated free port)."
            ),
            show_default=False,
            callback=validate_port_option,
        ),
    ] = None,
    web_port: Annotated[
        int | None,
        typer.Option(
            "--web-port",
            "-w",
            envvar="TRANSPORT_MATTERS_WEB_PORT",
            help=(
                "Port for the embedded web UI (default: kernel-allocated free port)."
            ),
            show_default=False,
            callback=validate_port_option,
        ),
    ] = None,
    storage_dir: Annotated[
        Path | None,
        typer.Option(
            "--storage-dir",
            "-d",
            envvar="TRANSPORT_MATTERS_STORAGE_DIR",
            help=(
                "Directory for captured exchanges, rules, and the index. "
                "Defaults to `~/.transport-matters`."
            ),
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    codex_bin: Annotated[
        Path | None,
        typer.Option(
            "--codex-bin",
            help="Path to Codex (default: `codex` on PATH).",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    no_codex: Annotated[
        bool,
        typer.Option(
            "--no-codex",
            help="Run the proxy only; don't spawn Codex.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable verbose mitmproxy output (for troubleshooting).",
        ),
    ] = False,
    force_http_fallback: Annotated[
        bool,
        typer.Option(
            "--force-http-fallback",
            help=(
                "Test mode: short-circuit Codex's WebSocket upgrade with HTTP 426 "
                "to force the HTTPS Responses fallback path. Used to capture "
                "the HTTP wire format without changing Codex CLI config."
            ),
        ),
    ] = False,
    print_command: Annotated[
        bool,
        typer.Option(
            "--print-command",
            help="Print the resolved child invocations and exit without running them.",
        ),
    ] = False,
) -> None:
    """Start the Transport Matters workbench: proxy + Codex."""
    directory, codex_passthrough = _split_passthrough(ctx, directory)
    run_codex(
        directory=directory,
        codex_passthrough=codex_passthrough,
        proxy_port=proxy_port,
        web_port=web_port,
        storage_dir=storage_dir,
        codex_bin=codex_bin,
        no_codex=no_codex,
        debug=debug,
        force_http_fallback=force_http_fallback,
        print_command=print_command,
        require_addon=_require_addon,
        require_force_http_fallback_addon=_require_force_http_fallback_addon,
        resolve_mitmdump=_resolve_mitmdump,
        which=shutil.which,
        port_in_use=_port_in_use,
        allocate_port_pair=allocate_port_pair,
        resolve_codex_ca_certificate=resolve_codex_ca_certificate,
        print_client_banner=_print_client_banner,
        run_client_with_retry=_run_client_with_retry,
        print_contention_error=_print_contention_error,
    )


@main.command(
    cls=_PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def doctor() -> None:
    """Diagnose the local environment."""
    run_doctor()


@main.command(
    cls=_PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def paths(
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help=(
                "Resolve paths for a specific workspace — either a slug from "
                f"`{CLI_COMMAND} list` or a directory to canonicalise as a CWD. "
                "Defaults to the current working directory."
            ),
            show_default=False,
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of aligned text."),
    ] = False,
) -> None:
    """Show where Transport Matters stores things and where the package lives."""
    resolve_paths(workspace=workspace, as_json=as_json)


@main.command(
    name="list",
    cls=_PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def list_instances(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of aligned text."),
    ] = False,
) -> None:
    """List live Transport Matters instances."""
    _list_instances(as_json=as_json)


@main.command(
    cls=_PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def version() -> None:
    """Print the installed Transport Matters version and exit."""
    typer.echo(__version__)
