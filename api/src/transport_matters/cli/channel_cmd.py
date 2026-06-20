"""``transport-matters channel`` command group."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import psycopg
import typer
from psycopg import sql

from transport_matters import env_keys
from transport_matters.channel import (
    ChannelSpec,
    activate_channel,
    all_channel_specs,
)
from transport_matters.config import (
    DATABASE_URL_GUIDANCE,
    MissingDatabaseConfigError,
    Settings,
    database_url_with_database_name,
    get_settings,
)
from transport_matters.session.migrate import MigrationError, apply_migrations, migration_head
from transport_matters.session.pool import connect
from transport_matters.storage_roots import default_storage_root

from .desktop_runtime import desktop_record_path, read_live_desktop_record
from .identity import CLI_COMMAND

if TYPE_CHECKING:
    from psycopg import Connection
    from psycopg.rows import DictRow

_MAINTENANCE_DATABASE = "postgres"

channel_app = typer.Typer(
    no_args_is_help=True,
    help="List, prepare, and promote Transport Matters channels.",
)


@dataclass(frozen=True, slots=True)
class EnsureDatabaseResult:
    database_name: str
    created: bool


def repo_root() -> Path:
    """Return the source checkout root that owns the root justfile."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "justfile").is_file() and (parent / "api").is_dir():
            return parent
    raise RuntimeError("could not find the Transport Matters source checkout")


def ensure_channel_database(
    spec: ChannelSpec,
    configured_database_url: str,
) -> EnsureDatabaseResult:
    """Create the channel database if absent, then migrate it to head."""
    database_url = database_url_with_database_name(
        configured_database_url,
        spec.database_name,
    )
    maintenance_url = database_url_with_database_name(
        configured_database_url,
        _MAINTENANCE_DATABASE,
    )
    created = _create_database_if_absent(maintenance_url, spec.database_name)
    apply_migrations(database_url)
    return EnsureDatabaseResult(
        database_name=spec.database_name,
        created=created,
    )


def run_install_local(root: Path) -> None:
    """Run the source checkout install recipe used by stable."""
    subprocess.run(["just", "install-local"], cwd=root, check=True)


@channel_app.command("list")
def list_channels() -> None:
    """Print every configured channel."""
    rows = [
        (
            "id",
            "home",
            "database",
            "proxy",
            "web",
            "pid",
            "app",
            "badge",
        ),
        *(
            (
                spec.id,
                str(spec.home),
                spec.database_name,
                str(spec.proxy_port),
                str(spec.web_port),
                _desktop_pid(spec),
                spec.electron_app_name,
                spec.badge.text if spec.badge is not None else "none",
            )
            for spec in all_channel_specs()
        ),
    ]
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for row in rows:
        typer.echo("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _desktop_pid(spec: ChannelSpec) -> str:
    record = read_live_desktop_record(
        desktop_record_path(default_storage_root(spec.id).expanduser().resolve())
    )
    return "" if record is None else str(record.pid)


@channel_app.command("ensure-db")
def ensure_db(
    channel: Annotated[
        str | None,
        typer.Argument(
            help="Channel id to prepare. Defaults to TRANSPORT_MATTERS_CHANNEL or stable.",
        ),
    ] = None,
) -> None:
    """Create and migrate the configured database for a channel."""
    spec = _activate_channel_or_exit(channel)
    try:
        configured_database_url = _configured_database_url_or_exit(get_settings())
        result = ensure_channel_database(spec, configured_database_url)
    except MissingDatabaseConfigError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    except (psycopg.Error, OSError) as exc:
        typer.secho(
            f"error: could not prepare channel database: {exc}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(2) from exc
    except MigrationError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    state = "created" if result.created else "exists"
    typer.echo(f"database {result.database_name}: {state}")
    typer.secho(f"session store at head ({migration_head()})", fg=typer.colors.GREEN)


@channel_app.command("promote")
def promote(
    from_channel: Annotated[str, typer.Argument(help="Source channel.")],
    to_channel: Annotated[str, typer.Argument(help="Destination channel.")],
) -> None:
    """Promote code from preview to stable."""
    if (from_channel, to_channel) != ("preview", "stable"):
        typer.secho(
            "error: only preview stable is supported for channel promote.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    try:
        root = repo_root()
    except RuntimeError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    try:
        run_install_local(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        typer.secho(f"error: install-local failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.echo("stable launch command:")
    typer.echo(f"  {CLI_COMMAND} desktop --channel stable")


def _activate_channel_or_exit(channel: str | None) -> ChannelSpec:
    try:
        return activate_channel(channel)
    except (KeyError, ValueError) as exc:
        requested = channel if channel is not None else os.environ.get(env_keys.CHANNEL, "stable")
        typer.secho(f"error: unknown channel {requested!r}.", fg=typer.colors.RED, err=True)
        typer.echo(f"Run `{CLI_COMMAND} channel list` to see available channels.", err=True)
        raise typer.Exit(2) from exc


def _configured_database_url_or_exit(settings: Settings) -> str:
    configured = settings.database_url or settings.database.url
    if configured:
        return configured
    raise MissingDatabaseConfigError(DATABASE_URL_GUIDANCE)


def _create_database_if_absent(maintenance_url: str, database_name: str) -> bool:
    with connect(maintenance_url, autocommit=True) as conn:
        if _database_exists(conn, database_name):
            return False
        try:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        except psycopg.errors.DuplicateDatabase:
            return False
    return True


def _database_exists(conn: Connection[DictRow], database_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s",
        (database_name,),
    ).fetchone()
    return row is not None
