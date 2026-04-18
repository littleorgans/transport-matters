"""Help text blobs and plain-text renderers for the manicure CLI.

The philosophy, stolen wholesale from `attention-matters`:

- Every command has a short description, a long description, and at least
  one runnable example in the help epilog.
- No dead ends. When something fails, we tell the user what to try next.

Rendered verbatim as plain text via `_PlainGroup` / `_PlainCommand` so
Typer's Rich chrome never competes with the hand-tuned layout.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    import click
from typer.core import TyperCommand, TyperGroup

from manicure import __version__

_ROOT_HELP = dedent(f"""\
    manicure {__version__} — context control plane for coding agents

    Commands
      claude    Run proxy + Claude Code together (one command, one session)
      codex     Run proxy + Codex together (ChatGPT transport path)
      list      List live manicure instances
      doctor    Diagnose the local environment
      paths     Show storage and package locations
      version   Print installed version

    Quick start
      $ manicure claude              # proxy + claude in cwd
      $ manicure claude ~/project    # proxy + claude in ~/project
      $ manicure codex               # proxy + codex in cwd
      $ manicure claude --no-claude  # proxy only (old UX)

    Environment
      MANICURE_PROXY_PORT       pin proxy port (default: kernel-allocated)
      MANICURE_WEB_PORT         pin web UI port (default: kernel-allocated)
      MANICURE_STORAGE_DIR      data dir (default ~/.manicure/)
      MANICURE_UPSTREAM_URL     upstream API (default https://api.anthropic.com)

    Options
      -V, --version             Show version and exit
      -h, --help                Show this message and exit

    https://github.com/srobinson/manicure
""")

_CLAUDE_HELP = dedent("""\
    Start the manicure workbench: proxy + Claude Code.

    Spawns mitmproxy in reverse-proxy mode with the manicure addon,
    waits for it to come up, then launches `claude` in the working
    directory you point at (defaults to cwd). Ctrl+C tears both down.

    Arguments
      [DIRECTORY]               Working dir for Claude Code (default: cwd)

    Options
      -p, --proxy-port INT      Proxy listener port (default: kernel-allocated free port)
      -w, --web-port INT        Web UI port (default: kernel-allocated free port)
      -u, --upstream URL        Upstream provider URL (default https://api.anthropic.com)
      -d, --storage-dir PATH    Data directory (default ~/.manicure/)
          --claude-bin PATH     Path to Claude Code (default: `claude` on PATH)
          --no-claude           Run proxy only; skip spawning Claude Code
          --no-system-prompt    Skip the auto-injected manicure system prompt
          --debug               Verbose mitmproxy output
          --print-command       Print the child invocations and exit
      -h, --help                Show this message and exit

    Port allocation
      With no `--proxy-port` / `--web-port` flags, manicure asks the
      kernel for two free TCP ports on localhost and uses those. This
      lets two `manicure claude` sessions in different workspaces run
      concurrently without colliding on the default 8787 / 8788. Any
      port you pin explicitly is honoured as-is.

    System-prompt injection
      Unless you pass `--no-system-prompt`, manicure prepends an
      `--append-system-prompt` argument to the claude invocation
      announcing the proxy URL and inspector URL for the session. If
      you supply your own `--system-prompt` or `--append-system-prompt`
      in pass-through, manicure's injection is skipped — your prompt
      wins.

    Pass-through to claude
      Anything after `--` is forwarded verbatim to the claude subprocess.
      Manicure does not validate or rewrite these args; whatever claude
      accepts today it accepts here.
        $ manicure claude -- --help                 # claude's help
        $ manicure claude -- --model sonnet --resume
        $ manicure claude ~/proj -- -p "fix the bug"

      If the first pass-through token does not start with `-`, pass an
      explicit working directory first (e.g. `.`) so it isn't captured
      by `[DIRECTORY]`:
        $ manicure claude . -- "what is 2+2"

    Examples
      $ manicure claude
      $ manicure claude ~/my-project
      $ manicure claude --proxy-port 9000 --web-port 9001
      $ manicure claude --no-claude
      $ manicure claude --no-system-prompt
      $ manicure claude --claude-bin /opt/homebrew/bin/claude
      $ manicure claude --print-command
""")

_CODEX_HELP = dedent("""\
    Start the manicure workbench: proxy + Codex.

    Spawns mitmproxy in explicit proxy mode with the manicure addon,
    waits for it to come up, then launches `codex` in the working
    directory you point at (defaults to cwd). Ctrl+C tears both down.

    Arguments
      [DIRECTORY]               Working dir for Codex (default: cwd)

    Options
      -p, --proxy-port INT      Proxy listener port (default: kernel-allocated free port)
      -w, --web-port INT        Web UI port (default: kernel-allocated free port)
      -d, --storage-dir PATH    Data directory (default ~/.manicure/)
          --codex-bin PATH      Path to Codex (default: `codex` on PATH)
          --no-codex            Run proxy only; skip spawning Codex
          --debug               Verbose mitmproxy output
          --print-command       Print the child invocations and exit
      -h, --help                Show this message and exit

    Proxy environment
      Manicure exports `HTTP_PROXY` and `HTTPS_PROXY` to the codex
      subprocess, pointed at the local listener. If your shell already
      exports `CODEX_CA_CERTIFICATE`, manicure validates that path and
      passes it through. Otherwise it snapshots the active Python trust
      roots, appends `~/.mitmproxy/mitmproxy-ca-cert.pem`, and exports
      the merged bundle as a process scoped `CODEX_CA_CERTIFICATE`.

    Pass-through to codex
      Anything after `--` is forwarded verbatim to the codex subprocess.
      Manicure does not validate or rewrite these args.
        $ manicure codex -- --help
        $ manicure codex -- exec "fix the failing test"
        $ manicure codex ~/proj -- exec --model gpt-5 "trace startup"

      If the first pass-through token does not start with `-`, pass an
      explicit working directory first (e.g. `.`) so it isn't captured
      by `[DIRECTORY]`:
        $ manicure codex . -- exec "what failed?"

    Examples
      $ manicure codex
      $ manicure codex ~/my-project
      $ manicure codex --proxy-port 9000 --web-port 9001
      $ manicure codex --no-codex
      $ manicure codex --codex-bin /opt/homebrew/bin/codex
      $ manicure codex --print-command
""")

_DOCTOR_HELP = dedent("""\
    Diagnose the local environment.

    Checks: Python version, mitmproxy, packaged addon, web bundle,
    storage directory, default ports. Exit 0 if all pass, 1 otherwise.

    Options
      -h, --help                Show this message and exit

    Examples
      $ manicure doctor
      $ manicure doctor && manicure claude
""")

_PATHS_HELP = dedent("""\
    Show where manicure stores things and where the package lives.

    The `storage` entry resolves per-workspace: the live manifest's
    storage_dir when an instance is running in the target CWD, and
    the default ~/.manicure/workspaces/{slug}/{hash}/ root otherwise.

    Options
          --workspace SLUG|DIR  Target a specific workspace (default: CWD)
          --json                Emit JSON instead of aligned text
      -h, --help                Show this message and exit

    Examples
      $ manicure paths
      $ manicure paths --json
      $ manicure paths --workspace helioy-manicure-api
      $ manicure paths --workspace ~/other-project
""")

_VERSION_HELP = dedent("""\
    Print the installed manicure version and exit.

    Equivalent to manicure --version.

    Options
      -h, --help                Show this message and exit
""")

_LIST_HELP = dedent("""\
    List live manicure instances.

    Scans ~/.manicure/workspaces/ for manifests and probes each one's
    lock file to discriminate live instances from stale manifests.
    Stale manifests are reaped transparently. The probe never blocks
    on the lock — safe to run with a live instance in the same CWD.

    Options
          --json                Emit JSON instead of aligned text
      -h, --help                Show this message and exit

    Examples
      $ manicure list
      $ manicure list --json
""")

_SUBCOMMAND_HELP = {
    "claude": _CLAUDE_HELP,
    "start": _CLAUDE_HELP,
    "codex": _CODEX_HELP,
    "list": _LIST_HELP,
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
