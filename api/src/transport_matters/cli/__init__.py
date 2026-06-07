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

Re-exports (`SIGNAL_EXIT`, `ProcessSupervisor`, `port_in_use`,
`wait_for_port_ready`, `print_banner`, `run_children`) stay at
package scope so existing imports and most test monkeypatch paths
remain valid.
"""

from __future__ import annotations

import shutil
import sysconfig
from functools import partial
from importlib.resources import files
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Annotated, TypedDict

import typer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from importlib.resources.abc import Traversable

from transport_matters import __version__
from transport_matters.lock import WorkspaceLock, WorkspaceLocked
from transport_matters.manifest import Manifest
from transport_matters.manifest import write as manifest_write
from transport_matters.supervisor import SIGNAL_EXIT, ProcessSupervisor
from transport_matters.workspace import run_root, workspace_id, workspace_root

from .banner import print_banner, print_client_banner
from .codex_cmd import run_codex
from .db_cmd import db_app
from .desktop_cmd import prepare_desktop_launch
from .diagnose import run_doctor
from .help import PlainCommand, PlainGroup
from .identity import CLI_COMMAND
from .instances import list_instances as list_instances_impl
from .launch_options import (  # noqa: TC001
    AgentHomeDirOption,
    AgentOption,
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
    RouteOption,
    StorageDirOption,
    WebPortOption,
    WorkDirOption,
)
from .launch_runtime import resolve_mitmdump_executable
from .net import port_in_use, wait_for_port_ready
from .paths import resolve_paths
from .ports import PortAllocationError, allocate_port_pair
from .prompt import inject_system_prompt, user_supplied_system_prompt
from .runner import BindFailure, run_children, run_client_with_retry
from .start_cmd import run_start
from .trust import resolve_codex_ca_certificate


class _SharedDesktopLaunchKwargs(TypedDict):
    directory: Path | None
    proxy_port: int | None
    web_port: int | None
    storage_dir: Path | None
    home_dir: Path | None
    debug: bool
    print_command: bool
    require_addon: Callable[[], Traversable]
    resolve_mitmdump: Callable[[], str | None]
    which: Callable[[str], str | None]
    port_in_use: Callable[[int], bool]
    allocate_port_pair: Callable[[], tuple[int, int]]
    run_client_with_retry: Callable[..., None]


__all__ = [
    "SIGNAL_EXIT",
    "BindFailure",
    "Manifest",
    "PortAllocationError",
    "ProcessSupervisor",
    "WorkspaceLock",
    "WorkspaceLocked",
    "allocate_port_pair",
    "inject_system_prompt",
    "list_instances",
    "main",
    "manifest_write",
    "port_in_use",
    "print_banner",
    "run_children",
    "run_client_with_retry",
    "run_root",
    "user_supplied_system_prompt",
    "wait_for_port_ready",
    "workspace_id",
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
    work_dir: WorkDirOption = None,
    proxy_port: ProxyPortOption = None,
    web_port: WebPortOption = None,
    upstream: ClaudeUpstreamOption = "https://api.anthropic.com",
    storage_dir: StorageDirOption = None,
    home_dir: AgentHomeDirOption = None,
    claude_bin: ClaudeBinOption = None,
    no_claude: NoClaudeOption = False,
    no_system_prompt: NoSystemPromptOption = False,
    debug: DebugOption = False,
    print_command: PrintCommandOption = False,
) -> None:
    """Start the Transport Matters workbench: proxy + Claude Code."""
    claude_passthrough = _split_passthrough(ctx)
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
        require_addon=_require_addon,
        resolve_mitmdump=partial(
            resolve_mitmdump_executable,
            which=shutil.which,
            get_scripts_dir=sysconfig.get_path,
        ),
        which=shutil.which,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
        inject_system_prompt=inject_system_prompt,
        user_supplied_system_prompt=user_supplied_system_prompt,
        print_banner=print_banner,
        run_client_with_retry=run_client_with_retry,
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
    codex_passthrough = _split_passthrough(ctx)
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
        require_addon=_require_addon,
        require_force_http_fallback_addon=_require_force_http_fallback_addon,
        resolve_mitmdump=partial(
            resolve_mitmdump_executable,
            which=shutil.which,
            get_scripts_dir=sysconfig.get_path,
        ),
        which=shutil.which,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
        resolve_codex_ca_certificate=resolve_codex_ca_certificate,
        print_client_banner=print_client_banner,
        run_client_with_retry=run_client_with_retry,
    )


@main.command(
    name="desktop",
    cls=PlainCommand,
    no_args_is_help=False,
    context_settings={
        "help_option_names": ["-h", "--help"],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def desktop(
    ctx: typer.Context,
    agent: AgentOption = "claude",
    route: RouteOption = "canvas",
    work_dir: WorkDirOption = None,
    proxy_port: ProxyPortOption = None,
    web_port: WebPortOption = None,
    storage_dir: StorageDirOption = None,
    home_dir: AgentHomeDirOption = None,
    debug: DebugOption = False,
    print_command: PrintCommandOption = False,
    upstream: ClaudeUpstreamOption = "https://api.anthropic.com",
    claude_bin: ClaudeBinOption = None,
    no_claude: NoClaudeOption = False,
    no_system_prompt: NoSystemPromptOption = False,
    codex_bin: CodexBinOption = None,
    no_codex: NoCodexOption = False,
    force_http_fallback: ForceHttpFallbackOption = False,
) -> None:
    """Start the canvas desktop viewer alongside an interactive agent."""
    passthrough = _split_passthrough(ctx)
    plan = prepare_desktop_launch(
        ctx=ctx,
        agent=agent,
        route=route,
        base_run_client_with_retry=run_client_with_retry,
        launch_viewer=not print_command,
    )
    resolved_home_dir = _resolve_home_dir_option(
        home_dir,
        create=not print_command,
    )
    shared_launch_kwargs: _SharedDesktopLaunchKwargs = {
        "directory": work_dir,
        "proxy_port": proxy_port,
        "web_port": web_port,
        "storage_dir": storage_dir,
        "home_dir": resolved_home_dir,
        "debug": debug,
        "print_command": print_command,
        "require_addon": _require_addon,
        "resolve_mitmdump": partial(
            resolve_mitmdump_executable,
            which=shutil.which,
            get_scripts_dir=sysconfig.get_path,
        ),
        "which": shutil.which,
        "port_in_use": port_in_use,
        "allocate_port_pair": allocate_port_pair,
        "run_client_with_retry": plan.run_client_with_retry,
    }
    if plan.agent == "claude":
        run_start(
            **shared_launch_kwargs,
            claude_passthrough=passthrough,
            upstream=upstream,
            claude_bin=claude_bin,
            no_claude=no_claude,
            no_system_prompt=no_system_prompt,
            inject_system_prompt=inject_system_prompt,
            user_supplied_system_prompt=user_supplied_system_prompt,
            print_banner=print_banner,
        )
        return

    run_codex(
        **shared_launch_kwargs,
        codex_passthrough=passthrough,
        codex_bin=codex_bin,
        no_codex=no_codex,
        force_http_fallback=force_http_fallback,
        require_force_http_fallback_addon=_require_force_http_fallback_addon,
        resolve_codex_ca_certificate=resolve_codex_ca_certificate,
        print_client_banner=print_client_banner,
    )


@main.command(
    cls=PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def doctor() -> None:
    """Diagnose the local environment."""
    run_doctor()


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
def list_instances(
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
