"""Startup banner rendered right before the children spawn."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from pathlib import Path


def _print_banner(
    *,
    proxy_port: int,
    web_port: int,
    upstream: str,
    working_dir: Path,
    no_claude: bool,
) -> None:
    typer.secho("manicure starting", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  proxy    http://localhost:{proxy_port}  →  {upstream}")
    typer.echo(f"  web UI   http://localhost:{web_port}")
    if no_claude:
        typer.echo("")
        typer.echo("  point your client at the proxy:")
        typer.echo(f"    ANTHROPIC_BASE_URL=http://localhost:{proxy_port} claude")
    else:
        typer.echo(f"  claude   MANICURE_CWD={working_dir}")
    typer.echo("")
