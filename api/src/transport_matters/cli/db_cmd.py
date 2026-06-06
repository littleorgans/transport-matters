"""``transport-matters db`` command group: session-store schema status and upgrade.

Operators normally never run these: the backend auto-migrates to head on launch. They
exist as an explicit escape hatch and for transparency, and share the one migrator in
:mod:`transport_matters.session.migrate`.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import typer

from transport_matters.config import MissingDatabaseConfigError, get_settings, resolve_database_url
from transport_matters.session.migrate import (
    MigrationError,
    apply_migrations,
    current_revision,
    migration_head,
)

db_app = typer.Typer(
    no_args_is_help=True,
    help="Inspect and upgrade the Transport Matters session-store schema.",
)


def _redact(url: str) -> str:
    parts = urlsplit(url)
    if parts.password:
        netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
        parts = parts._replace(netloc=netloc)
    return urlunsplit(parts)


def _resolve_or_exit() -> str:
    try:
        return resolve_database_url(get_settings())
    except MissingDatabaseConfigError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


@db_app.command("status")
def status() -> None:
    """Show the configured database, its current revision, and the target head."""
    database_url = _resolve_or_exit()
    head = migration_head()
    try:
        current = current_revision(database_url)
    except Exception as exc:
        typer.secho(f"error: cannot reach the session store: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"database: {_redact(database_url)}")
    typer.echo(f"current:  {current or '(unmigrated)'}")
    typer.echo(f"head:     {head}")
    if current == head:
        typer.secho("up to date", fg=typer.colors.GREEN)
    else:
        typer.secho(
            "migration pending - run `transport-matters db upgrade`",
            fg=typer.colors.YELLOW,
        )


@db_app.command("upgrade")
def upgrade() -> None:
    """Apply pending session-store migrations (advisory-locked, idempotent)."""
    database_url = _resolve_or_exit()
    try:
        apply_migrations(database_url)
    except MigrationError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.secho(f"session store at head ({migration_head()})", fg=typer.colors.GREEN)
