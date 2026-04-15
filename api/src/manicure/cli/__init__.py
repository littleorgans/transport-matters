"""Manicure command-line interface.

This package is the `[project.scripts]` entry point installed by `pip` /
`uv tool install` / the `install.sh` bootstrap. It exposes one real
command (`start`) plus three support commands (`doctor`, `paths`,
`version`).

Module layout:
  help.py     — all static help text + plain-text renderers
  net.py      — port probing helpers
  banner.py   — startup banner
  runner.py   — the supervisor-driven lifecycle for `start`
  __init__.py — typer app, command bodies, and the re-export surface

Re-exports (`SIGNAL_EXIT`, `ProcessSupervisor`, `_port_in_use`,
`_wait_for_port_ready`, `_print_banner`, `_run_children`) are kept at
package scope so existing imports and most test monkeypatch paths stay
valid. `_run_children`'s own dependencies (`ProcessSupervisor`,
`_wait_for_port_ready`) are looked up from `manicure.cli.runner` — tests
that drive `_run_children` patch them there.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from datetime import UTC, datetime
from importlib.resources import as_file, files
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import typer

from manicure import __version__
from manicure.lock import WorkspaceLock, WorkspaceLocked
from manicure.manifest import Manifest
from manicure.manifest import write as manifest_write
from manicure.supervisor import SIGNAL_EXIT, ProcessSupervisor
from manicure.workspace import workspace_id, workspace_root, workspace_storage

from .banner import _print_banner
from .diagnose import run_doctor
from .help import _PlainCommand, _PlainGroup
from .instances import _list_instances, _print_contention_error
from .net import _port_in_use, _wait_for_port_ready, validate_port_option
from .paths import resolve_paths
from .ports import PortAllocationError, allocate_port_pair
from .prompt import inject_system_prompt, user_supplied_system_prompt
from .runner import BindFailure, _run_children, _run_with_retry

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


# --------------------------------------------------------------------------- #
# Typer app                                                                   #
# --------------------------------------------------------------------------- #

main = typer.Typer(
    name="manicure",
    cls=_PlainGroup,
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# --------------------------------------------------------------------------- #
# Root callback (global flags)                                                #
# --------------------------------------------------------------------------- #


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"manicure {__version__}")
        raise typer.Exit()


@main.callback()
def _root(
    _version: Annotated[  # noqa: FBT002 — typer expects this shape
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


# --------------------------------------------------------------------------- #
# start                                                                       #
# --------------------------------------------------------------------------- #


@main.command(
    cls=_PlainCommand,
    no_args_is_help=False,
    context_settings={
        "help_option_names": ["-h", "--help"],
        # Keep everything after the first `--` (or any unknown flag) so
        # we can forward it to claude verbatim. `ignore_unknown_options`
        # prevents click from erroring on claude flags it doesn't know;
        # `allow_extra_args` exposes them via `ctx.args`. We leave
        # `allow_interspersed_args` at its default (True) so existing
        # invocations like `manicure start /dir --proxy-port 9000`
        # keep working.
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def start(
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
            envvar="MANICURE_PROXY_PORT",
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
            envvar="MANICURE_WEB_PORT",
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
            envvar="MANICURE_UPSTREAM_URL",
            help="Upstream provider base URL (reverse proxy target).",
        ),
    ] = "https://api.anthropic.com",
    storage_dir: Annotated[
        Path | None,
        typer.Option(
            "--storage-dir",
            "-d",
            envvar="MANICURE_STORAGE_DIR",
            help=(
                "Directory for captured exchanges, rules, and the index. "
                "Defaults to `~/.manicure`."
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
            help=(
                "Skip the auto-injected manicure system prompt "
                "(URLs to the proxy + inspector). On by default."
            ),
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
    """Start the manicure workbench: proxy + Claude Code.

    Spawns a mitmproxy instance in reverse-proxy mode with the manicure
    addon, then launches Claude Code in `DIRECTORY` (cwd by default) with
    `ANTHROPIC_BASE_URL` pointed at the proxy. Ctrl+C tears both down.

    Use `--no-claude` for the proxy-only workflow (mitmdump in the
    foreground, you run `claude` yourself in another terminal).

    Everything after a literal `--` on the command line is forwarded to
    the claude subprocess untouched: `manicure start -- --model sonnet`.
    """
    # 0. Split the raw argv into (manicure, pass-through). Click has
    # already stripped options and the `DIRECTORY` positional; anything
    # left lives in `ctx.args`. But when the user writes
    # `manicure start -- --foo` with NO directory, click silently eats
    # the `--` terminator and the next token (`--foo`) ends up bound
    # to `directory`. Detect that case by inspecting the basename of
    # the resolved directory path: real dirs don't start with `-`.
    claude_passthrough: list[str] = list(ctx.args)
    if directory is not None and directory.name.startswith("-"):
        claude_passthrough = [directory.name, *claude_passthrough]
        directory = None
    # With a directory present, click surfaces the `--` as a literal in
    # `ctx.args`; without one, it was already consumed. Strip the
    # leading `--` so we forward only the tail.
    if claude_passthrough and claude_passthrough[0] == "--":
        claude_passthrough = claude_passthrough[1:]

    # --no-claude means "proxy only" — forwarding args to a subprocess
    # we aren't spawning is nonsense. Fail fast and loud before any
    # side effects, including `--print-command` output.
    if no_claude and claude_passthrough:
        typer.secho(
            "error: --no-claude is incompatible with pass-through args after '--'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    # 1. Locate the packaged addon module.
    addon_traversable = files("manicure") / "addon.py"
    if not addon_traversable.is_file():
        typer.secho(
            "error: could not locate the manicure mitmproxy addon.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(
            "The package may be corrupted. Try reinstalling:\n"
            "  uv tool install --force manicure",
            err=True,
        )
        raise typer.Exit(2)

    # 2. Check that mitmdump is reachable on PATH.
    mitmdump = shutil.which("mitmdump")
    if mitmdump is None:
        typer.secho(
            "error: `mitmdump` was not found on PATH.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(
            "mitmproxy ships as a runtime dependency of manicure, so this\n"
            "usually means the install did not link the console scripts.\n"
            "\n"
            "Try one of:\n"
            "  uv tool install --force manicure     # reinstall as a tool\n"
            "  pipx reinstall manicure              # if you used pipx\n"
            "  pip install --force-reinstall manicure",
            err=True,
        )
        raise typer.Exit(2)

    # 3. Resolve Claude Code binary (unless --no-claude).
    claude_path: str | None = None
    if not no_claude:
        claude_path = (
            str(claude_bin) if claude_bin is not None else shutil.which("claude")
        )
        if claude_path is None:
            typer.secho(
                "error: `claude` was not found on PATH.",
                fg=typer.colors.RED,
                err=True,
            )
            typer.echo(
                "Install Claude Code, or point at an existing install:\n"
                "  npm install -g @anthropic-ai/claude-code\n"
                "  # or\n"
                "  manicure start --claude-bin /path/to/claude\n"
                "  # or run proxy-only:\n"
                "  manicure start --no-claude",
                err=True,
            )
            raise typer.Exit(2)

    # 4. Validate upstream URL before passing to mitmdump.
    parsed_url = urlparse(upstream)
    if not parsed_url.scheme or not parsed_url.hostname:
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

    # 5. Resolve working directory. Typer's resolve_path makes the value
    # absolute when the user passes one; when they don't, we fall back to
    # the caller's cwd at invocation time (not at import time).
    working_dir = directory if directory is not None else Path.cwd()
    if not working_dir.is_dir():
        typer.secho(
            f"error: directory does not exist: {working_dir}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    # 5a. Capture which ports were user-pinned BEFORE we mutate the
    # variables — the retry loop downstream needs to know which slots
    # we are allowed to re-allocate when a bind conflict surfaces.
    proxy_user_supplied = proxy_port is not None
    web_user_supplied = web_port is not None

    # 5b. Resolve ports — allocate a free pair if the user didn't pin
    # them. We always call `allocate_port_pair` when at least one port
    # is unset; the allocated value for the *other* slot is discarded
    # if the user supplied it. The brief extra socket() pair is cheap.
    if proxy_port is None or web_port is None:
        try:
            allocated_proxy, allocated_web = allocate_port_pair()
        except PortAllocationError as exc:
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc
        if proxy_port is None:
            proxy_port = allocated_proxy
        if web_port is None:
            web_port = allocated_web

    # 7. Pre-spawn fast-fail for pinned-and-busy. Unpinned ports skip
    # the preflight: if the kernel just allocated the port, it is free
    # by definition (modulo the very TOCTOU window the retry loop
    # exists to handle). Catching the pinned case here gives a clearer
    # error than the post-spawn log scan would.
    for label, flag, port, pinned in (
        ("proxy", "--proxy-port", proxy_port, proxy_user_supplied),
        ("web UI", "--web-port", web_port, web_user_supplied),
    ):
        if pinned and _port_in_use(port):
            typer.secho(
                f"error: {label} port {port} is already in use.",
                fg=typer.colors.RED,
                err=True,
            )
            typer.echo(
                "Another process is already bound to this port. Either stop it,\n"
                f"or pick a different port (omit {flag} to let manicure allocate one).",
                err=True,
            )
            raise typer.Exit(2)

    # 9. Resolve storage dir. Explicit `--storage-dir` still wins; the
    # fallback is per-workspace (`~/.manicure/workspaces/{slug}/{hash}/`)
    # so two live instances in different CWDs write to disjoint roots.
    # We deliberately skip `get_settings()` here — its `@lru_cache` plus
    # `MANICURE_STORAGE_DIR` env plumbing conflates "what the user set"
    # with "what we will set for the child", so we route around it.
    resolved_storage = (
        storage_dir if storage_dir is not None else workspace_storage(working_dir)
    )

    # Snapshot the user's raw passthrough so we can re-inject the
    # system-prompt URLs from scratch on each retry attempt — porting
    # the URLs forward in place would either inject twice or string-
    # replace the old ports inside an opaque blob.
    claude_passthrough_user = list(claude_passthrough)

    # 8. Build the child invocations. The addon `as_file` context wraps
    # the whole spawn region so the temporary path stays valid across
    # all retry attempts.
    with as_file(addon_traversable) as addon_path:

        def _build_invocation(
            *, proxy_port: int, web_port: int
        ) -> tuple[list[str], dict[str, str], list[str] | None]:
            """Build (mitmdump_argv, child_env, claude_argv) from current ports.

            Pure function over its args; rebuilt fresh each retry so the
            injected system-prompt URLs and env vars track the ports we
            actually plan to bind on this attempt.
            """
            passthrough = list(claude_passthrough_user)
            if (
                not no_claude
                and not no_system_prompt
                and not user_supplied_system_prompt(passthrough)
            ):
                passthrough = inject_system_prompt(
                    passthrough, proxy_port=proxy_port, web_port=web_port
                )
            env = os.environ.copy()
            # Unconditionally flow the resolved storage path through the
            # child env so the addon's lazy `get_settings()` picks up the
            # per-workspace root instead of falling back to the packaged
            # default `~/.manicure/`.
            env["MANICURE_STORAGE_DIR"] = str(resolved_storage)
            env["MANICURE_WEB_PORT"] = str(web_port)
            env["MANICURE_PROXY_PORT"] = str(proxy_port)
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
            claude_argv = (
                [claude_path, *passthrough] if claude_path is not None else None
            )
            return argv, env, claude_argv

        if print_command:
            mitmdump_argv, _env, claude_argv = _build_invocation(
                proxy_port=proxy_port, web_port=web_port
            )
            typer.echo(" ".join(mitmdump_argv))
            if claude_argv is not None:
                typer.echo(" ".join(claude_argv))
            raise typer.Exit(0)

        # 10. Acquire the workspace lock and drive the spawn lifecycle.
        # Contention raises `WorkspaceLocked` at `__enter__`; we
        # translate that into exit-2 without printing the banner.
        wid = workspace_id(working_dir)
        ws_root = workspace_root(working_dir)
        try:
            with WorkspaceLock(ws_root) as wslock:

                def _write_manifest_for(p_port: int, w_port: int) -> None:
                    manifest_write(
                        wslock.manifest_path,
                        Manifest(
                            cwd=str(working_dir),
                            pid=os.getpid(),
                            proxy_port=p_port,
                            web_port=w_port,
                            storage_dir=str(resolved_storage),
                            started_at=datetime.now(UTC).isoformat(),
                            manicure_version=__version__,
                            slug=wid.slug,
                            hash=wid.hash,
                        ),
                    )

                def _print_banner_for(p_port: int, w_port: int) -> None:
                    _print_banner(
                        proxy_port=p_port,
                        web_port=w_port,
                        upstream=upstream,
                        working_dir=working_dir,
                        no_claude=no_claude,
                    )

                try:
                    _run_with_retry(
                        proxy_port=proxy_port,
                        web_port=web_port,
                        proxy_user_supplied=proxy_user_supplied,
                        web_user_supplied=web_user_supplied,
                        build_invocation=lambda p, w: _build_invocation(
                            proxy_port=p, web_port=w
                        ),
                        print_banner_for=_print_banner_for,
                        write_manifest_for=_write_manifest_for,
                        resolved_storage=resolved_storage,
                        working_dir=working_dir,
                    )
                finally:
                    # Best-effort manifest cleanup. The lock itself is
                    # released by the outer `with` — that is truth; the
                    # manifest is advisory.
                    with contextlib.suppress(FileNotFoundError):
                        wslock.manifest_path.unlink()
        except WorkspaceLocked as exc:
            _print_contention_error(exc, working_dir)
            raise typer.Exit(2) from exc


# --------------------------------------------------------------------------- #
# doctor                                                                      #
# --------------------------------------------------------------------------- #


@main.command(
    cls=_PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def doctor() -> None:
    """Diagnose the local environment.

    Runs a short checklist of things that can go wrong between install
    and first run: Python version, mitmproxy availability, packaged
    addon, packaged web bundle, data directory writability, and the
    default ports.

    Each check prints one line. Failing checks include a hint for what
    to try next.
    """
    run_doctor()


# --------------------------------------------------------------------------- #
# paths                                                                       #
# --------------------------------------------------------------------------- #


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
                "`manicure list` or a directory to canonicalise as a CWD. "
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
    """Show where manicure stores things and where the package lives.

    The `storage` entry resolves per-workspace: the live manifest's
    ``storage_dir`` when an instance is running in the target CWD, and
    the default ``~/.manicure/workspaces/{slug}/{hash}/`` root
    otherwise. Useful for pointing other tools (editors, backups,
    log shippers) at the right files for a specific workspace.
    """
    resolve_paths(workspace=workspace, as_json=as_json)


# --------------------------------------------------------------------------- #
# list                                                                        #
# --------------------------------------------------------------------------- #


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
    """List live manicure instances.

    Scans ``~/.manicure/workspaces/`` for manifests, probes each
    sibling lock file to discriminate live instances from stale
    manifests, and prints the live ones. Stale entries are reaped
    transparently. No lock is ever taken for inspection.
    """
    _list_instances(as_json=as_json)


# --------------------------------------------------------------------------- #
# version                                                                     #
# --------------------------------------------------------------------------- #


@main.command(
    cls=_PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def version() -> None:
    """Print the installed manicure version and exit.

    Equivalent to `manicure --version`. Exposed as a subcommand so it
    composes nicely in shell pipelines.
    """
    typer.echo(__version__)
