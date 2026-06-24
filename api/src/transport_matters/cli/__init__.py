"""Transport Matters command-line interface.

This package is the `[project.scripts]` entry point installed by `pip` /
`uv tool install` / the `install.sh` bootstrap. It exposes two launch
commands (`claude`, `codex`, `desktop`) plus support commands (`doctor`, `paths`,
`list`, `version`).

Module layout:
  help.py         — all static help text + plain-text renderers
  net.py          — port probing helpers
  banner.py       — startup banner
  runner.py       — supervisor-driven child lifecycles
  start_cmd.py    — `transport-matters claude` implementation
  codex_cmd.py    — `transport-matters codex` implementation
  desktop_cmd.py  — `transport-matters desktop` validation + Electron viewer hook
  launch_runtime.py — shared launch plumbing
  __init__.py     — typer app, command registration, and re-exports

Package scope keeps only the CLI app and compatibility seams that current
callers import or patch. Import implementation helpers from their owning
modules.
"""

from __future__ import annotations

import os
import shutil
import sysconfig
from importlib.resources import files
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from collections.abc import Iterable
    from importlib.resources.abc import Traversable

    from transport_matters.captured_run import CapturedRunDependencies

from transport_matters import __version__, env_keys
from transport_matters.captured_run import default_claude_run_dependencies
from transport_matters.channel import activate_channel
from transport_matters.lock import WorkspaceLock
from transport_matters.supervisor import SIGNAL_EXIT
from transport_matters.workspace import workspace_root

from .banner import print_banner as _print_banner
from .banner import print_client_banner
from .channel_cmd import channel_app
from .codex_cmd import run_codex
from .db_cmd import db_app
from .desktop_cmd import (
    DESKTOP_BACKEND_COMMAND,
    run_desktop_backend_server,
    run_desktop_detached,
    run_desktop_launch,
)
from .diagnose import run_doctor
from .help import PlainCommand, PlainGroup
from .identity import CLI_COMMAND
from .instances import list_instances as list_instances_impl
from .launch_options import (
    CLAUDE_UPSTREAM_DEFAULT,
    AgentHomeDirOption,
    ChannelOption,
    ClaudeBinOption,
    ClaudeUpstreamOption,
    CodexBinOption,
    DebugOption,
    ForceHttpFallbackOption,
    NoClaudeOption,
    NoCodexOption,
    NoSystemPromptOption,
    PrintCommandOption,
    ProxyPortOption,
    StorageDirOption,
    WebPortOption,
    WorkDirOption,
)
from .net import port_in_use
from .paths import resolve_paths
from .ports import allocate_port_pair
from .prompt import inject_system_prompt as _inject_system_prompt
from .prompt import user_supplied_system_prompt as _user_supplied_system_prompt
from .runner import BindFailure, run_children
from .runner import run_client_with_retry as _run_client_with_retry
from .start_cmd import run_start
from .tail_cmd import run_tail
from .trust import resolve_codex_ca_certificate

__all__ = [
    "SIGNAL_EXIT",
    "BindFailure",
    "WorkspaceLock",
    "allocate_port_pair",
    "main",
    "port_in_use",
    "run_children",
    "workspace_root",
]


main = typer.Typer(
    name=CLI_COMMAND,
    cls=PlainGroup,
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    context_settings={"help_option_names": ["-h", "--help"]},
)
main.add_typer(db_app, name="db")
main.add_typer(channel_app, name="channel")


def _split_passthrough(ctx: typer.Context) -> list[str]:
    """Return raw pass-through args for the client."""
    passthrough: list[str] = list(ctx.args)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    return passthrough


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


def _claude_run_dependencies() -> CapturedRunDependencies:
    return default_claude_run_dependencies(
        require_addon=_require_addon,
        which=shutil.which,
        get_scripts_dir=sysconfig.get_path,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
        inject_system_prompt=_inject_system_prompt,
        user_supplied_system_prompt=_user_supplied_system_prompt,
    )


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


def _resolve_home_dir_option(home_dir: Path | None, *, create: bool) -> Path | None:
    """Resolve ``--agent-home-dir`` once before child cwd changes can affect it."""
    if home_dir is None:
        return None
    resolved = home_dir.expanduser().resolve()
    if not create:
        return resolved
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        typer.secho(
            f"error: could not create home directory: {resolved}",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(f"  {exc}", err=True)
        raise typer.Exit(2) from exc
    return resolved


def _activate_channel_or_exit(channel: str | None) -> None:
    try:
        activate_channel(channel)
    except (KeyError, ValueError) as exc:
        requested = channel if channel is not None else os.environ.get(env_keys.CHANNEL, "stable")
        typer.secho(
            f"error: unknown channel {requested!r}.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(f"Run `{CLI_COMMAND} channel list` to see available channels.", err=True)
        raise typer.Exit(2) from exc


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
    cls=PlainCommand,
    no_args_is_help=False,
    context_settings={
        "help_option_names": ["-h", "--help"],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def claude(
    ctx: typer.Context,
    channel: ChannelOption = None,
    work_dir: WorkDirOption = None,
    proxy_port: ProxyPortOption = None,
    web_port: WebPortOption = None,
    upstream: ClaudeUpstreamOption = CLAUDE_UPSTREAM_DEFAULT,
    storage_dir: StorageDirOption = None,
    home_dir: AgentHomeDirOption = None,
    claude_bin: ClaudeBinOption = None,
    no_claude: NoClaudeOption = False,
    no_system_prompt: NoSystemPromptOption = False,
    debug: DebugOption = False,
    print_command: PrintCommandOption = False,
) -> None:
    """Start the Transport Matters workbench: proxy + Claude Code."""
    _activate_channel_or_exit(channel)
    claude_passthrough = _split_passthrough(ctx)
    dependencies = _claude_run_dependencies()
    resolved_home_dir = _resolve_home_dir_option(
        home_dir,
        create=not print_command,
    )
    run_start(
        directory=work_dir,
        claude_passthrough=claude_passthrough,
        proxy_port=proxy_port,
        web_port=web_port,
        upstream=upstream,
        storage_dir=storage_dir,
        home_dir=resolved_home_dir,
        claude_bin=claude_bin,
        no_claude=no_claude,
        no_system_prompt=no_system_prompt,
        debug=debug,
        print_command=print_command,
        channel=channel,
        require_addon=dependencies.require_addon,
        resolve_mitmdump=dependencies.resolve_mitmdump,
        which=dependencies.which,
        port_in_use=dependencies.port_in_use,
        allocate_port_pair=dependencies.allocate_port_pair,
        inject_system_prompt=dependencies.inject_system_prompt,
        user_supplied_system_prompt=dependencies.user_supplied_system_prompt,
        print_banner=_print_banner,
        run_client_with_retry=_run_client_with_retry,
    )


@main.command(
    cls=PlainCommand,
    no_args_is_help=False,
    context_settings={
        "help_option_names": ["-h", "--help"],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def codex(
    ctx: typer.Context,
    channel: ChannelOption = None,
    work_dir: WorkDirOption = None,
    proxy_port: ProxyPortOption = None,
    web_port: WebPortOption = None,
    storage_dir: StorageDirOption = None,
    home_dir: AgentHomeDirOption = None,
    codex_bin: CodexBinOption = None,
    no_codex: NoCodexOption = False,
    debug: DebugOption = False,
    force_http_fallback: ForceHttpFallbackOption = False,
    print_command: PrintCommandOption = False,
) -> None:
    """Start the Transport Matters workbench: proxy + Codex."""
    _activate_channel_or_exit(channel)
    codex_passthrough = _split_passthrough(ctx)
    dependencies = _claude_run_dependencies()
    resolved_home_dir = _resolve_home_dir_option(
        home_dir,
        create=not print_command,
    )
    run_codex(
        directory=work_dir,
        codex_passthrough=codex_passthrough,
        proxy_port=proxy_port,
        web_port=web_port,
        storage_dir=storage_dir,
        home_dir=resolved_home_dir,
        codex_bin=codex_bin,
        no_codex=no_codex,
        debug=debug,
        force_http_fallback=force_http_fallback,
        print_command=print_command,
        channel=channel,
        require_addon=dependencies.require_addon,
        require_force_http_fallback_addon=_require_force_http_fallback_addon,
        resolve_mitmdump=dependencies.resolve_mitmdump,
        which=dependencies.which,
        port_in_use=dependencies.port_in_use,
        allocate_port_pair=dependencies.allocate_port_pair,
        resolve_codex_ca_certificate=resolve_codex_ca_certificate,
        print_client_banner=print_client_banner,
        run_client_with_retry=_run_client_with_retry,
    )


@main.command(
    name="desktop",
    cls=PlainCommand,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def desktop(
    channel: ChannelOption = None,
    work_dir: WorkDirOption = None,
    web_port: WebPortOption = None,
    storage_dir: StorageDirOption = None,
    foreground: Annotated[
        bool,
        typer.Option(
            "--foreground",
            help="Run the desktop backend in the foreground and stream logs.",
        ),
    ] = False,
    force_restart: Annotated[
        bool,
        typer.Option(
            "--force-restart",
            help="Explicitly terminate the recorded desktop backend before restart.",
        ),
    ] = False,
) -> None:
    """Start the canvas desktop viewer and backend server."""
    _activate_channel_or_exit(channel)
    if foreground:
        if force_restart:
            typer.secho(
                "error: --force-restart is only supported for detached desktop launch.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(2)
        run_desktop_launch(
            channel=channel,
            work_dir=work_dir,
            web_port=web_port,
            storage_dir=storage_dir,
        )
        return
    run_desktop_detached(
        channel=channel,
        work_dir=work_dir,
        web_port=web_port,
        storage_dir=storage_dir,
        force_restart=force_restart,
    )


@main.command(
    cls=PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def tail(
    channel: Annotated[
        str | None,
        typer.Argument(
            help="Channel id to tail. Defaults to TRANSPORT_MATTERS_CHANNEL or stable.",
        ),
    ] = None,
    follow: Annotated[
        bool,
        typer.Option("--follow", "-f", help="Continue printing appended log lines."),
    ] = False,
    lines: Annotated[
        int,
        typer.Option("--lines", "-n", min=0, help="Number of existing log lines to print."),
    ] = 100,
) -> None:
    """Print detached desktop backend logs."""
    run_tail(channel=channel, lines=lines, follow=follow)


@main.command(
    name=DESKTOP_BACKEND_COMMAND,
    cls=PlainCommand,
    hidden=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def desktop_backend(
    channel: ChannelOption = None,
    work_dir: WorkDirOption = None,
    proxy_port: ProxyPortOption = None,
    web_port: WebPortOption = None,
    storage_dir: StorageDirOption = None,
    debug: DebugOption = False,
) -> None:
    """Run the internal desktop backend server."""
    _activate_channel_or_exit(channel)
    run_desktop_backend_server(
        channel=channel,
        work_dir=work_dir,
        proxy_port=proxy_port,
        web_port=web_port,
        storage_dir=storage_dir,
        debug=debug,
    )


@main.command(
    cls=PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def doctor(
    reap_orphans: Annotated[
        bool,
        typer.Option(
            "--reap-orphans",
            help="Terminate stale captured runs (running longer than --older-than seconds).",
        ),
    ] = False,
    older_than: Annotated[
        int,
        typer.Option(
            "--older-than",
            help="Age threshold in seconds for orphan candidates (default 300).",
        ),
    ] = 300,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip per-run confirmation prompts when reaping orphans.",
        ),
    ] = False,
) -> None:
    """Diagnose the local environment."""
    run_doctor(
        reap_orphans=reap_orphans,
        older_than_seconds=older_than,
        confirm=(lambda _run: True) if yes else None,
    )


@main.command(
    cls=PlainCommand,
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
    cls=PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def _list_instances(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of aligned text."),
    ] = False,
) -> None:
    """List live Transport Matters instances."""
    list_instances_impl(as_json=as_json)


@main.command(
    cls=PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def version() -> None:
    """Print the installed Transport Matters version and exit."""
    typer.echo(__version__)
