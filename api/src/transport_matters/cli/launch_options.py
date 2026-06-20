"""Reusable Typer option aliases for launch commands."""

# ruff: noqa: UP040

from pathlib import Path
from typing import Annotated, TypeAlias

import typer

from transport_matters import captured_run, env_keys

from .net import validate_port_option

CLAUDE_UPSTREAM_DEFAULT = captured_run.CLAUDE_UPSTREAM_DEFAULT
WorkDirOption: TypeAlias = Annotated[
    Path | None,
    typer.Option(
        "--work-dir",
        help="Working directory for the agent and canvas. Defaults to cwd.",
        show_default=False,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
]
ChannelOption: TypeAlias = Annotated[
    str | None,
    typer.Option(
        "--channel",
        envvar=env_keys.CHANNEL,
        help="Transport Matters channel. Defaults to stable.",
        show_default=False,
    ),
]
ProxyPortOption: TypeAlias = Annotated[
    int | None,
    typer.Option(
        "--proxy-port",
        "-p",
        envvar=env_keys.PROXY_PORT,
        help="Proxy listener port. Defaults to the active channel proxy port.",
        show_default=False,
        callback=validate_port_option,
    ),
]
WebPortOption: TypeAlias = Annotated[
    int | None,
    typer.Option(
        "--web-port",
        "-w",
        envvar=env_keys.WEB_PORT,
        help="Embedded web UI port. Defaults to the active channel web port.",
        show_default=False,
        callback=validate_port_option,
    ),
]
StorageDirOption: TypeAlias = Annotated[
    Path | None,
    typer.Option(
        "--storage-dir",
        "-d",
        # No envvar: a launch must not inherit a parent session's
        # TRANSPORT_MATTERS_STORAGE_DIR as its --storage-dir, or nested
        # runs would co-reside in the parent's store. The addon (pydantic
        # settings) and `paths` env-first still read the env var directly.
        help=(
            "Directory for captured exchanges, rules, and the index. "
            "Defaults to `~/.transport-matters`."
        ),
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
]
AgentHomeDirOption: TypeAlias = Annotated[
    Path | None,
    typer.Option(
        "--agent-home-dir",
        help="Directory for agent config and transcripts. Defaults to the agent native home.",
        file_okay=False,
        dir_okay=True,
        resolve_path=False,
    ),
]
DebugOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--debug",
        help="Enable verbose mitmproxy output for troubleshooting.",
    ),
]
PrintCommandOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--print-command",
        help="Print the resolved child invocations and exit without running them.",
    ),
]
ClaudeUpstreamOption: TypeAlias = Annotated[
    str,
    typer.Option(
        "--upstream",
        "-u",
        envvar=env_keys.UPSTREAM_URL,
        help="Upstream provider base URL for the reverse proxy target.",
    ),
]
ClaudeBinOption: TypeAlias = Annotated[
    Path | None,
    typer.Option(
        "--claude-bin",
        help="Path to the Claude Code binary. Defaults to `claude` on PATH.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
]
NoClaudeOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--no-claude",
        help="Run the proxy only. Do not spawn Claude Code.",
    ),
]
NoSystemPromptOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--no-system-prompt",
        help="Skip the auto-injected Transport Matters system prompt.",
    ),
]
CodexBinOption: TypeAlias = Annotated[
    Path | None,
    typer.Option(
        "--codex-bin",
        help="Path to Codex. Defaults to `codex` on PATH.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
]
NoCodexOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--no-codex",
        help="Run the proxy only. Do not spawn Codex.",
    ),
]
ForceHttpFallbackOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--force-http-fallback",
        help=(
            "Test mode: short-circuit Codex's WebSocket upgrade with HTTP 426 "
            "to force the HTTPS Responses fallback path."
        ),
    ),
]
