"""Startup banner rendered right before the children spawn."""

from typing import TYPE_CHECKING

import typer

from .identity import PRODUCT_LABEL
from .net import loopback_http_url

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def print_client_banner(
    *,
    proxy_port: int,
    web_port: int,
    proxy_target: str,
    working_dir: Path,
    client_label: str,
    proxy_hint: Sequence[str] | None = None,
) -> None:
    """Render the launch banner for a managed client or proxy-only mode."""
    typer.secho(f"{PRODUCT_LABEL} starting", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  proxy    {loopback_http_url(proxy_port)}  →  {proxy_target}")
    typer.echo(f"  web UI   {loopback_http_url(web_port)}")
    if proxy_hint is not None:
        typer.echo("")
        typer.echo("  point your client at the proxy:")
        for line in proxy_hint:
            typer.echo(f"    {line}")
    else:
        typer.echo(f"  {client_label:<7} TRANSPORT_MATTERS_CWD={working_dir}")
    typer.echo("")


def print_banner(
    *,
    proxy_port: int,
    web_port: int,
    upstream: str,
    working_dir: Path,
    no_claude: bool,
) -> None:
    proxy_hint = None
    if no_claude:
        proxy_hint = (f"ANTHROPIC_BASE_URL={loopback_http_url(proxy_port)} claude",)
    print_client_banner(
        proxy_port=proxy_port,
        web_port=web_port,
        proxy_target=upstream,
        working_dir=working_dir,
        client_label="claude",
        proxy_hint=proxy_hint,
    )
