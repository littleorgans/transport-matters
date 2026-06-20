"""Help text blobs and plain-text renderers for the Transport Matters CLI.

The philosophy, stolen wholesale from `attention-matters`:

- Every command has a short description, a long description, and at least
  one runnable example in the help epilog.
- No dead ends. When something fails, we tell the user what to try next.

Rendered verbatim as plain text via `PlainGroup` / `PlainCommand` so
Typer's Rich chrome never competes with the hand-tuned layout.
"""

from textwrap import dedent
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    import click
from typer.core import TyperCommand, TyperGroup

from transport_matters import __version__

from .identity import CLI_COMMAND, PRODUCT_LABEL

_ROOT_HELP = dedent(f"""\
    {PRODUCT_LABEL} {__version__}
    Context control plane for coding agents

    Commands
  claude    Run proxy + Claude Code together (one command, one session)
  codex     Run proxy + Codex together (ChatGPT transport path)
  desktop   Open the desktop canvas and local backend
  channel   List, prepare, and promote channels
  tail      Print detached desktop backend logs
  list      List live Transport Matters instances
      doctor    Diagnose the local environment
      paths     Show storage and package locations
      version   Print installed version

    Quick start
      $ {CLI_COMMAND} claude              # proxy + claude in cwd
      $ {CLI_COMMAND} claude --work-dir ~/project
      $ {CLI_COMMAND} codex               # proxy + codex in cwd
      $ {CLI_COMMAND} claude --no-claude  # proxy only

  Environment
      TRANSPORT_MATTERS_DATABASE_URL     Postgres session store (postgresql://USER:PASS@HOST:PORT/DB)
      TRANSPORT_MATTERS_CHANNEL          active channel (default stable)
      TRANSPORT_MATTERS_HOME             config/data root for settings.toml (default ~/.transport-matters)
      TRANSPORT_MATTERS_PROXY_PORT       pin proxy port (default: active channel port)
      TRANSPORT_MATTERS_WEB_PORT         pin web UI port (default: active channel port)
      TRANSPORT_MATTERS_STORAGE_DIR      addon/paths/doctor data dir; launches use per-run storage
      TRANSPORT_MATTERS_AGENT_HOME_DIR   managed agent home for config/transcripts (default: native)
      TRANSPORT_MATTERS_UPSTREAM_URL     upstream API (default https://api.anthropic.com)

    Options
      -V, --version             Show version and exit
      -h, --help                Show this message and exit

    https://github.com/littleorgans/transport-matters
""")

_CLAUDE_HELP = dedent(f"""\
    Start the Transport Matters workbench: proxy + Claude Code.

    Spawns mitmproxy in reverse-proxy mode with the Transport Matters addon,
    waits for it to come up, then launches `claude` in the working
    directory you point at (defaults to cwd). Ctrl+C tears both down.

    Options
          --work-dir PATH       Working dir for Claude Code (default: cwd)
          --channel ID          Channel id (default: stable)
      -p, --proxy-port INT      Proxy listener port (default: active channel port)
      -w, --web-port INT        Web UI port (default: active channel port)
      -u, --upstream URL        Upstream provider URL (default https://api.anthropic.com)
      -d, --storage-dir PATH    Data directory (default ~/.transport-matters/)
          --agent-home-dir PATH       Claude Code home for config and transcripts
          --claude-bin PATH     Path to Claude Code (default: `claude` on PATH)
          --no-claude           Run proxy only; skip spawning Claude Code
          --no-system-prompt    Skip the auto-injected Transport Matters system prompt
          --debug               Verbose mitmproxy output
          --print-command       Print the child invocations and exit
      -h, --help                Show this message and exit

    Port allocation
      With no `--proxy-port` / `--web-port` flags, Transport Matters uses the
      active channel's deterministic proxy and web ports. Any port you pin
      explicitly is honoured as-is.

    System-prompt injection
      Unless you pass `--no-system-prompt`, Transport Matters prepends an
      `--append-system-prompt` argument to the claude invocation
      announcing the proxy URL and inspector URL for the session. If
      you supply your own `--system-prompt` or `--append-system-prompt`
      in pass-through, Transport Matters injection is skipped; your prompt
      wins.

    Pass-through to claude
      Anything after `--` is forwarded verbatim to the claude subprocess.
      Transport Matters does not validate or rewrite these args; whatever claude
      accepts today it accepts here.
        $ {CLI_COMMAND} claude -- --help                 # claude's help
        $ {CLI_COMMAND} claude -- --model sonnet --resume
        $ {CLI_COMMAND} claude --work-dir ~/proj -- -p "fix the bug"
        $ {CLI_COMMAND} claude -- "what is 2+2"

    Examples
      $ {CLI_COMMAND} claude
      $ {CLI_COMMAND} claude --work-dir ~/my-project
      $ {CLI_COMMAND} claude --proxy-port 9000 --web-port 9001
      $ {CLI_COMMAND} claude --no-claude
      $ {CLI_COMMAND} claude --no-system-prompt
      $ {CLI_COMMAND} claude --agent-home-dir ~/.claude-test
      $ {CLI_COMMAND} claude --claude-bin /opt/homebrew/bin/claude
      $ {CLI_COMMAND} claude --print-command
""")

_CODEX_HELP = dedent(f"""\
    Start the Transport Matters workbench: proxy + Codex.

    Spawns mitmproxy in explicit proxy mode with the Transport Matters addon,
    waits for it to come up, then launches `codex` in the working
    directory you point at (defaults to cwd). Ctrl+C tears both down.

    Options
          --work-dir PATH       Working dir for Codex (default: cwd)
          --channel ID          Channel id (default: stable)
      -p, --proxy-port INT      Proxy listener port (default: active channel port)
      -w, --web-port INT        Web UI port (default: active channel port)
      -d, --storage-dir PATH    Data directory (default ~/.transport-matters/)
          --agent-home-dir PATH       Codex home for config and transcripts
          --codex-bin PATH      Path to Codex (default: `codex` on PATH)
          --no-codex            Run proxy only; skip spawning Codex
          --debug               Verbose mitmproxy output
          --force-http-fallback Test mode: short-circuit Codex's WebSocket upgrade
                                with HTTP 426 to force the HTTPS Responses path
          --print-command       Print the child invocations and exit
      -h, --help                Show this message and exit

    Proxy environment
      Transport Matters exports `HTTP_PROXY` and `HTTPS_PROXY` to the codex
      subprocess, pointed at the local listener. If your shell already
      exports `CODEX_CA_CERTIFICATE`, Transport Matters validates that path and
      passes it through. Otherwise it snapshots the active Python trust
      roots, appends `~/.mitmproxy/mitmproxy-ca-cert.pem`, and exports
      the merged bundle as a process scoped `CODEX_CA_CERTIFICATE`.

    Pass-through to codex
      Anything after `--` is forwarded verbatim to the codex subprocess.
      Transport Matters does not validate or rewrite these args.
        $ {CLI_COMMAND} codex -- --help
        $ {CLI_COMMAND} codex -- exec "fix the failing test"
        $ {CLI_COMMAND} codex --work-dir ~/proj -- exec --model gpt-5 "trace startup"
        $ {CLI_COMMAND} codex -- exec "what failed?"

    Examples
      $ {CLI_COMMAND} codex
      $ {CLI_COMMAND} codex --work-dir ~/my-project
      $ {CLI_COMMAND} codex --proxy-port 9000 --web-port 9001
      $ {CLI_COMMAND} codex --no-codex
      $ {CLI_COMMAND} codex --agent-home-dir ~/.codex-test
      $ {CLI_COMMAND} codex --codex-bin /opt/homebrew/bin/codex
    $ {CLI_COMMAND} codex --print-command
""")

_DESKTOP_HELP = dedent(f"""\
    Start the Transport Matters desktop canvas.

    Starts the local backend detached by default and opens the Electron canvas.
    The command returns immediately. Start Claude or Codex from captured panes
    inside the desktop UI.

    Options
          --work-dir PATH        Initial workspace hint for the canvas (default: cwd)
          --channel ID           Channel id (default: stable)
      -w, --web-port INT         Web UI port (default: active channel port)
      -d, --storage-dir PATH     Data directory (default ~/.transport-matters/)
          --foreground           Keep backend in the foreground and stream logs
      -h, --help                 Show this message and exit

    Examples
      $ {CLI_COMMAND} desktop
      $ {CLI_COMMAND} desktop --work-dir ~/my-project
      $ {CLI_COMMAND} desktop --web-port 9001
      $ {CLI_COMMAND} desktop --foreground
""")

_DOCTOR_HELP = dedent(f"""\
    Diagnose the local environment.

    Checks: Python version, mitmproxy, packaged addon, web bundle,
    storage directory, default ports. Exit 0 if all pass, 1 otherwise.

    Options
      -h, --help                Show this message and exit

    Examples
      $ {CLI_COMMAND} doctor
      $ {CLI_COMMAND} doctor && {CLI_COMMAND} claude
""")

_PATHS_HELP = dedent(f"""\
    Show where Transport Matters stores things and where the package lives.

    The `storage` entry resolves per-workspace: the live manifest's
    storage_dir when an instance is running in the target CWD, and
    the default ~/.transport-matters/workspaces/{{slug}}/{{hash}}/ root otherwise.

    Options
          --workspace SLUG|DIR  Target a specific workspace (default: CWD)
          --json                Emit JSON instead of aligned text
      -h, --help                Show this message and exit

    Examples
      $ {CLI_COMMAND} paths
      $ {CLI_COMMAND} paths --json
      $ {CLI_COMMAND} paths --workspace transport-matters-api
      $ {CLI_COMMAND} paths --workspace ~/other-project
""")

_TAIL_HELP = dedent(f"""\
    Print detached desktop backend logs.

    Reads the channel scoped desktop.log written by detached desktop launches.
    Without --follow, prints the last N lines and exits. With --follow, keeps
    polling for appended lines until Ctrl C.

    Options
      -f, --follow             Continue printing appended log lines
      -n, --lines INT          Number of existing log lines to print (default 100)
      -h, --help               Show this message and exit

    Examples
      $ {CLI_COMMAND} tail preview
      $ {CLI_COMMAND} tail -f preview
""")

_VERSION_HELP = dedent(f"""\
    Print the installed Transport Matters version and exit.

    Equivalent to {CLI_COMMAND} --version.

    Options
      -h, --help                Show this message and exit
""")

_LIST_HELP = dedent(f"""\
    List live Transport Matters instances.

    Scans ~/.transport-matters/workspaces/ for manifests and probes each one's
    lock file to discriminate live instances from stale manifests.
    Stale manifests are reaped transparently. The probe never blocks
    on the lock — safe to run with a live instance in the same CWD.

    Options
          --json                Emit JSON instead of aligned text
      -h, --help                Show this message and exit

    Examples
      $ {CLI_COMMAND} list
      $ {CLI_COMMAND} list --json
""")

_SUBCOMMAND_HELP = {
    "claude": _CLAUDE_HELP,
    "codex": _CODEX_HELP,
    "desktop": _DESKTOP_HELP,
    "tail": _TAIL_HELP,
    "list": _LIST_HELP,
    "doctor": _DOCTOR_HELP,
    "paths": _PATHS_HELP,
    "version": _VERSION_HELP,
}


class PlainGroup(TyperGroup):
    """Typer group that renders help as plain text."""

    def format_help(self, ctx: click.Context, formatter: Any) -> None:
        typer.echo(_ROOT_HELP, nl=False)


class PlainCommand(TyperCommand):
    """Typer command that renders help as plain text."""

    def format_help(self, ctx: click.Context, formatter: Any) -> None:
        text = _SUBCOMMAND_HELP.get(self.name or "", "")
        typer.echo(text, nl=False)
