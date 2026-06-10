"""Session store reachability checks for launch paths."""

import psycopg

from transport_matters import env_keys
from transport_matters.config import (
    MissingDatabaseConfigError,
    get_settings,
    resolve_database_url,
)

__all__ = ["check_session_store", "session_store_setup_help"]

_PREFLIGHT_CONNECT_TIMEOUT_S = 5


def session_store_setup_help() -> str:
    """Return operator setup guidance for a missing or unreachable session store."""
    return (
        "Transport Matters records sessions in a Postgres store. Set one up, then relaunch:\n"
        "  - Local or cloud Postgres: point Transport Matters at it\n"
        f"      export {env_keys.DATABASE_URL}=postgresql://USER:PASS@HOST:PORT/DBNAME\n"
        "      (or edit [database] url in settings.toml under "
        f"${env_keys.HOME}, default ~/.transport-matters)\n"
        "  - Docker (local dev): from the repo root run\n"
        "      docker compose up -d\n"
        "      (the scaffolded settings.example.toml URL targets this database)\n"
        "See QUICKSTART.md for the full setup."
    )


def check_session_store() -> str | None:
    """Return an error message if the session store is unconfigured or unreachable.

    Resolves the database URL from settings/env, then opens a short connection. Returns
    ``None`` when the store is reachable so the caller may proceed.
    """
    try:
        database_url = resolve_database_url(get_settings())
    except MissingDatabaseConfigError as exc:
        return f"session store is not configured: {exc}"
    try:
        with psycopg.connect(database_url, connect_timeout=_PREFLIGHT_CONNECT_TIMEOUT_S) as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError as exc:
        return f"cannot reach the session store at the configured URL: {exc}"
    return None
