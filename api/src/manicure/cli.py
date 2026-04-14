"""Manicure command-line interface.

This module is the `[project.scripts]` entry point installed by `pip` / `uv
tool install` / the `install.sh` bootstrap. It exposes one real command
(`start`) plus three support commands (`doctor`, `paths`, `version`).

The philosophy, stolen wholesale from `attention-matters`:

- Every command has a short description, a long description, and at least
  one runnable example in the help epilog.
- No dead ends. When something fails, we tell the user what to try next.
- Nothing here is business logic. `start` hands off to mitmdump via
  `os.execvpe` so the Python CLI process gets out of the way and signals
  propagate cleanly to the proxy.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
from importlib.resources import as_file, files
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlparse

import typer

if TYPE_CHECKING:
    import click
from typer.core import TyperCommand, TyperGroup

from manicure import __version__
from manicure.config import get_settings

# --------------------------------------------------------------------------- #
# Custom help — plain text, no Rich chrome                                    #
# --------------------------------------------------------------------------- #

_ROOT_HELP = dedent(f"""\
    manicure {__version__} — context control plane for coding agents

    Commands
      start     Run the reverse proxy + web UI
      doctor    Diagnose the local environment
      paths     Show storage and package locations
      version   Print installed version

    Quick start
      $ manicure start
      $ ANTHROPIC_BASE_URL=http://localhost:8787 claude

      Web UI  http://localhost:8788

    Environment
      MANICURE_PROXY_PORT       proxy port (default 8787)
      MANICURE_WEB_PORT         web UI port (default 8788)
      MANICURE_STORAGE_DIR      data dir (default ~/.manicure/)
      MANICURE_UPSTREAM_URL     upstream API (default https://api.anthropic.com)

    Options
      -V, --version             Show version and exit
      -h, --help                Show this message and exit

    https://github.com/srobinson/manicure
""")

_START_HELP = dedent("""\
    Start the reverse proxy and embedded web UI.

    Spawns mitmproxy in reverse-proxy mode with the manicure addon.
    Point your coding agent at http://localhost:<proxy-port> and open
    http://localhost:<web-port> in a browser.

    Options
      -p, --proxy-port INT      Proxy listener port (default 8787)
      -w, --web-port INT        Web UI port (default 8788)
      -u, --upstream URL        Upstream provider URL (default https://api.anthropic.com)
      -d, --storage-dir PATH    Data directory (default ~/.manicure/)
          --debug               Verbose mitmproxy output
          --print-command       Print the mitmdump invocation and exit
      -h, --help                Show this message and exit

    Examples
      $ manicure start
      $ manicure start --proxy-port 9000 --web-port 9001
      $ manicure start --print-command
      $ manicure start --debug
""")

_DOCTOR_HELP = dedent("""\
    Diagnose the local environment.

    Checks: Python version, mitmproxy, packaged addon, web bundle,
    storage directory, default ports. Exit 0 if all pass, 1 otherwise.

    Options
      -h, --help                Show this message and exit

    Examples
      $ manicure doctor
      $ manicure doctor && manicure start
""")

_PATHS_HELP = dedent("""\
    Show where manicure stores things and where the package lives.

    Options
          --json                Emit JSON instead of aligned text
      -h, --help                Show this message and exit

    Examples
      $ manicure paths
      $ manicure paths --json
""")

_VERSION_HELP = dedent("""\
    Print the installed manicure version and exit.

    Equivalent to manicure --version.

    Options
      -h, --help                Show this message and exit
""")

_SUBCOMMAND_HELP = {
    "start": _START_HELP,
    "doctor": _DOCTOR_HELP,
    "paths": _PATHS_HELP,
    "version": _VERSION_HELP,
}


class _PlainGroup(TyperGroup):
    """Typer group that renders help as plain text."""

    def format_help(self, ctx: click.Context, formatter: Any) -> None:
        typer.echo(_ROOT_HELP, nl=False)


class _PlainCommand(TyperCommand):
    """Typer command that renders help as plain text."""

    def format_help(self, ctx: click.Context, formatter: Any) -> None:
        text = _SUBCOMMAND_HELP.get(self.name or "", "")
        typer.echo(text, nl=False)


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
    context_settings={"help_option_names": ["-h", "--help"]},
)
def start(
    proxy_port: Annotated[
        int,
        typer.Option(
            "--proxy-port",
            "-p",
            envvar="MANICURE_PROXY_PORT",
            help="Port for the reverse-proxy listener (your client points at this).",
        ),
    ] = 8787,
    web_port: Annotated[
        int,
        typer.Option(
            "--web-port",
            "-w",
            envvar="MANICURE_WEB_PORT",
            help="Port for the embedded web UI.",
        ),
    ] = 8788,
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
            help="Print the resolved `mitmdump` invocation and exit without running it.",
        ),
    ] = False,
) -> None:
    """Start the manicure workbench (reverse proxy + web UI).

    Spawns a mitmproxy instance in reverse-proxy mode with the manicure
    addon loaded. The addon boots an embedded FastAPI server on the web
    port inside mitmproxy's asyncio loop, so you get the full workbench
    from one command.

    Point your coding agent at `http://localhost:<proxy-port>` via
    `ANTHROPIC_BASE_URL` and open `http://localhost:<web-port>` in a
    browser.
    """
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

    # 3. Validate upstream URL before passing to mitmdump.
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

    # 4. Build env vars for the subprocess (isolated from current process).
    child_env = os.environ.copy()
    if storage_dir is not None:
        child_env["MANICURE_STORAGE_DIR"] = str(storage_dir)
    child_env["MANICURE_WEB_PORT"] = str(web_port)
    child_env["MANICURE_PROXY_PORT"] = str(proxy_port)

    # 5. Verify ports are free.
    for label, port in (("proxy", proxy_port), ("web UI", web_port)):
        if _port_in_use(port):
            typer.secho(
                f"error: {label} port {port} is already in use.",
                fg=typer.colors.RED,
                err=True,
            )
            typer.echo(
                "Another process is already bound to this port. Either stop it,\n"
                f"or pick a different port with `--{'proxy' if label == 'proxy' else 'web'}-port`.",
                err=True,
            )
            raise typer.Exit(2)

    # 6. Build the final invocation.
    with as_file(addon_traversable) as addon_path:
        argv = [
            "mitmdump",
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

        if print_command:
            typer.echo(" ".join(argv))
            raise typer.Exit(0)

        _print_banner(proxy_port=proxy_port, web_port=web_port, upstream=upstream)

        # Hand the process off to mitmdump. Signals now go straight to it —
        # our CLI frame disappears. Nothing after this line runs on success.
        try:
            os.execvpe(mitmdump, argv, child_env)
        except OSError as exc:
            typer.secho(
                f"error: failed to exec mitmdump: {exc}",
                fg=typer.colors.RED,
                err=True,
            )
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
    failures: list[str] = []

    def _ok(label: str, detail: str = "") -> None:
        suffix = f" — {detail}" if detail else ""
        typer.secho(f"  ok    {label}{suffix}", fg=typer.colors.GREEN)

    def _fail(label: str, hint: str) -> None:
        failures.append(label)
        typer.secho(f"  fail  {label}", fg=typer.colors.RED, err=True)
        for line in hint.splitlines():
            typer.echo(f"        {line}", err=True)

    typer.echo("manicure doctor")
    typer.echo(f"  version: {__version__}")
    typer.echo("")

    # Python version (we require 3.12+)
    py = sys.version_info
    if py >= (3, 12):
        _ok("python", f"{py.major}.{py.minor}.{py.micro}")
    else:
        _fail(
            "python",
            f"manicure requires Python >= 3.12, found {py.major}.{py.minor}.\n"
            "Install a newer Python via https://docs.astral.sh/uv/ or pyenv.",
        )

    # mitmdump on PATH
    mitmdump = shutil.which("mitmdump")
    if mitmdump:
        _ok("mitmdump", mitmdump)
    else:
        _fail(
            "mitmdump",
            "`mitmdump` was not found on PATH. Reinstall manicure:\n"
            "  uv tool install --force manicure",
        )

    # Packaged addon
    addon = files("manicure") / "addon.py"
    if addon.is_file():
        _ok("addon", str(addon))
    else:
        _fail(
            "addon",
            "The packaged mitmproxy addon is missing. Reinstall manicure:\n"
            "  uv tool install --force manicure",
        )

    # Packaged web bundle (optional — source installs may not have one)
    www_dir = files("manicure") / "www"
    www_index = www_dir / "index.html"
    if www_index.is_file():
        _ok("web bundle", str(www_dir))
    else:
        typer.secho(
            "  warn  web bundle — not shipped with this build",
            fg=typer.colors.YELLOW,
        )
        typer.echo("        The web UI will not load. This is expected for")
        typer.echo("        source checkouts; release wheels embed the bundle.")

    # Storage directory
    settings = get_settings()
    storage = Path(settings.storage_dir).expanduser()
    try:
        storage.mkdir(parents=True, exist_ok=True)
        probe = storage / ".manicure-doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _ok("storage", str(storage))
    except OSError as exc:
        _fail(
            "storage",
            f"Cannot write to {storage}: {exc}.\n"
            "Fix permissions or set `MANICURE_STORAGE_DIR` to a writable path.",
        )

    # Configured ports
    for label, port in (
        ("proxy port", settings.proxy_port),
        ("web port", settings.web_port),
    ):
        if _port_in_use(port):
            typer.secho(
                f"  warn  {label} {port} in use — pick a different port with --{label.split()[0]}-port",
                fg=typer.colors.YELLOW,
            )
        else:
            _ok(label, str(port))

    typer.echo("")
    if failures:
        typer.secho(
            f"{len(failures)} check(s) failed: {', '.join(failures)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    typer.secho("all checks passed", fg=typer.colors.GREEN)


# --------------------------------------------------------------------------- #
# paths                                                                       #
# --------------------------------------------------------------------------- #


@main.command(
    cls=_PlainCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def paths(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of aligned text."),
    ] = False,
) -> None:
    """Show where manicure stores things and where the package lives.

    Useful for pointing other tools (editors, backups, log shippers) at
    the right files.
    """
    settings = get_settings()
    package_root = Path(str(files("manicure")))
    addon_path = package_root / "addon.py"
    www_path = package_root / "www"
    storage = Path(settings.storage_dir).expanduser()

    entries = {
        "version": __version__,
        "package": str(package_root),
        "addon": str(addon_path),
        "www": str(www_path),
        "storage": str(storage),
        "exchanges": str(storage / "exchanges"),
        "rules": str(storage / "rules.json"),
        "index": str(storage / "index.jsonl"),
    }

    if as_json:
        import json

        typer.echo(json.dumps(entries, indent=2))
        return

    width = max(len(k) for k in entries)
    for key, value in entries.items():
        typer.echo(f"  {key.ljust(width)}  {value}")


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


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _port_in_use(port: int) -> bool:
    """Return True if *port* on localhost is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def _print_banner(*, proxy_port: int, web_port: int, upstream: str) -> None:
    typer.secho("manicure starting", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  proxy    http://localhost:{proxy_port}  →  {upstream}")
    typer.echo(f"  web UI   http://localhost:{web_port}")
    typer.echo("")
    typer.echo("  point your client at the proxy:")
    typer.echo(f"    ANTHROPIC_BASE_URL=http://localhost:{proxy_port} claude")
    typer.echo("")


if __name__ == "__main__":
    main()
