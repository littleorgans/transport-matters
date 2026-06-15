"""Body of the ``transport-matters doctor`` subcommand.

Split out from :mod:`transport_matters.cli` so the package entry point stays
under the 700-LOC invariant. The typer command itself stays in
``cli/__init__.py`` as a thin wrapper that calls :func:`run_doctor`.

Tests that previously patched ``transport_matters.cli.shutil.which`` /
``transport_matters.cli.port_in_use`` continue to work because those
re-exports are still resolved at call time inside ``run_doctor``'s own module.
"""

from __future__ import annotations

import shutil
import sys
import sysconfig
from datetime import UTC, timedelta
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import typer

from transport_matters import __version__
from transport_matters.capabilities import detect_clis
from transport_matters.config import (
    DATABASE_URL_GUIDANCE,
    MissingDatabaseConfigError,
    get_settings,
    resolve_database_url,
)
from transport_matters.session.migrate import current_revision, migration_head

from .identity import CLI_COMMAND, PRODUCT_LABEL
from .launch_runtime import resolve_mitmdump_executable
from .net import port_in_use
from .runs_health import fetch_runs, orphan_candidates, reap_run, runs_base_url

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

__all__ = ["report_runs_health", "run_doctor"]


def _session_store_failure(database_url: str, exc: Exception) -> str:
    """One concise line for an unreachable session store, no driver stack dump.

    A raw SQLAlchemy/psycopg ``OperationalError`` is a multi-line wall (every
    connection attempt, the sqlalche.me link). Classify the root cause and show
    only host:port, never the URL itself (it may carry a password).
    """
    root = getattr(exc, "orig", exc)
    text = str(root).lower()
    if "connection refused" in text:
        reason = "connection refused (is Postgres running?)"
    elif "authentication" in text or "password" in text:
        reason = "authentication failed"
    elif "does not exist" in text:
        reason = "database does not exist"
    elif "timeout" in text or "timed out" in text:
        reason = "connection timed out"
    else:
        reason = str(root).splitlines()[0].strip() or "connection failed"
    try:
        parts = urlsplit(database_url)
        target = f" at {parts.hostname}:{parts.port}" if parts.hostname else ""
    except ValueError:
        target = ""
    return f"cannot reach the session store{target} — {reason}"


def report_runs_health(
    *,
    reap_orphans: bool,
    older_than_seconds: int,
    confirm: Callable[[dict[str, object]], bool],
    now: datetime,
) -> None:
    """Report live-run health and optionally terminate stale candidates.

    Separated from :func:`run_doctor` so it stays unit-testable and keeps
    the parent function within the ~150-line budget.
    """
    settings = get_settings()
    base_url = runs_base_url(settings)
    older_than = timedelta(seconds=older_than_seconds)

    runs = fetch_runs(base_url)
    if runs is None:
        # API not running: runs are process-resident, so none can be orphaned.
        # Nothing actionable — stay silent rather than narrate a non-finding.
        return

    typer.echo(f"  ok    runs: {len(runs)} live")

    candidates = orphan_candidates(runs, older_than=older_than, now=now)
    if not candidates:
        return

    age_label = f"{older_than_seconds}s"
    typer.echo(f"\n  running > {age_label} (possible stale captured runs):")
    for run in candidates:
        run_id = run.get("runId", "?")
        cli = run.get("cli", "?")
        workspace_id = run.get("workspaceId", "?")
        created_at = run.get("createdAt")
        if created_at is not None:
            from datetime import datetime as _dt

            created_at_dt = _dt.fromisoformat(str(created_at))
            if created_at_dt.tzinfo is None:
                created_at_dt = created_at_dt.replace(tzinfo=UTC)
            age_secs = int((now.replace(tzinfo=UTC) - created_at_dt).total_seconds())
            age_str = f"{age_secs}s"
        else:
            age_str = "?"
        typer.echo(f"    {run_id}  {cli}  {workspace_id}  running {age_str}")

    if not reap_orphans:
        typer.echo(f"\n  hint: reap with: {CLI_COMMAND} doctor --reap-orphans")
        return

    typer.echo("")
    for run in candidates:
        run_id = run.get("runId", "?")
        if not confirm(run):
            typer.echo(f"  skip  {run_id}")
            continue
        ok = reap_run(base_url, str(run_id))
        if ok:
            typer.secho(f"  terminated  {run_id}", fg=typer.colors.GREEN)
        else:
            typer.secho(f"  failed  {run_id}", fg=typer.colors.RED, err=True)


def run_doctor(
    *,
    reap_orphans: bool = False,
    older_than_seconds: int = 300,
    confirm: Callable[[dict[str, object]], bool] | None = None,
) -> None:
    """Run the diagnostic checklist and exit non-zero on any failure.

    Each check prints one line. Failing checks include a hint for what
    to try next.
    """
    from datetime import datetime

    failures: list[str] = []

    def _ok(label: str, detail: str = "") -> None:
        suffix = f" — {detail}" if detail else ""
        typer.secho(f"  ok    {label}{suffix}", fg=typer.colors.GREEN)

    def _fail(label: str, hint: str) -> None:
        failures.append(label)
        typer.secho(f"  fail  {label}", fg=typer.colors.RED, err=True)
        for line in hint.splitlines():
            typer.echo(f"        {line}", err=True)

    typer.echo(f"{PRODUCT_LABEL} doctor")
    typer.echo(f"  version: {__version__}")
    typer.echo("")

    # Python version (we require 3.12+)
    py = sys.version_info
    if py >= (3, 12):
        _ok("python", f"{py.major}.{py.minor}.{py.micro}")
    else:
        _fail(
            "python",
            f"{PRODUCT_LABEL} requires Python >= 3.12, found {py.major}.{py.minor}.\n"
            "Install a newer Python via https://docs.astral.sh/uv/ or pyenv.",
        )

    # mitmdump on PATH
    mitmdump = resolve_mitmdump_executable(
        which=shutil.which,
        get_scripts_dir=sysconfig.get_path,
    )
    if mitmdump:
        _ok("mitmdump", mitmdump)
    else:
        _fail(
            "mitmdump",
            f"`mitmdump` was not found on PATH. Reinstall {PRODUCT_LABEL}:\n"
            f"  uv tool install --force {CLI_COMMAND}",
        )

    # Packaged addon
    addon = files("transport_matters") / "addon.py"
    if addon.is_file():
        _ok("addon", str(addon))
    else:
        _fail(
            "addon",
            f"The packaged mitmproxy addon is missing. Reinstall {PRODUCT_LABEL}:\n"
            f"  uv tool install --force {CLI_COMMAND}",
        )

    # Packaged web bundle (optional — source installs may not have one)
    www_dir = files("transport_matters") / "www"
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

    # Managed client CLIs.
    for name, capability in detect_clis().items():
        if capability.installed:
            _ok(name, capability.version or "version unknown")
        else:
            typer.secho(f"  warn  missing {name}", fg=typer.colors.YELLOW)

    # Storage directory
    settings = get_settings()
    storage = Path(settings.storage_dir).expanduser()
    try:
        storage.mkdir(parents=True, exist_ok=True)
        probe = storage / ".transport-matters-doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _ok("storage", str(storage))
    except OSError as exc:
        _fail(
            "storage",
            f"Cannot write to {storage}: {exc}.\n"
            "Fix permissions or set `TRANSPORT_MATTERS_STORAGE_DIR` "
            "for doctor/addon/paths storage checks. Launches choose per-run storage.",
        )

    # Configured ports — uses the *defaults* from Settings, so the user
    # learns whether their preferred ports are free even though
    # `transport-matters claude` itself now allocates dynamically.
    for label, port in (
        ("proxy port", settings.proxy_port),
        ("web port", settings.web_port),
    ):
        if port_in_use(port):
            typer.secho(
                f"  warn  {label} {port} in use — "
                f"pick a different port with --{label.split()[0]}-port",
                fg=typer.colors.YELLOW,
            )
        else:
            _ok(label, str(port))

    # Session store: configured, reachable, and at the migration head.
    try:
        database_url = resolve_database_url(settings)
    except MissingDatabaseConfigError as exc:
        _fail("session store", f"{exc}")
    else:
        try:
            current = current_revision(database_url)
        except Exception as exc:
            _fail(
                "session store",
                f"{_session_store_failure(database_url, exc)}\n{DATABASE_URL_GUIDANCE}",
            )
        else:
            head = migration_head()
            if current is None:
                _fail(
                    "session store",
                    "schema not initialised — run "
                    f"`{CLI_COMMAND} db upgrade` (launching also auto-migrates)",
                )
            elif current != head:
                _fail(
                    "session store",
                    f"schema behind head ({current} != {head}) — run `{CLI_COMMAND} db upgrade`",
                )
            else:
                _ok("session store", f"schema at {head}")

    # Live runs: read-only report; optionally terminate stale candidates.
    now = datetime.now(tz=UTC)

    def _default_confirm(run: dict[str, object]) -> bool:
        run_id = run.get("runId", "?")
        cli = run.get("cli", "?")
        cwd = run.get("cwd", "?")
        return typer.confirm(f"Reap run {run_id} ({cli} in {cwd})?")

    report_runs_health(
        reap_orphans=reap_orphans,
        older_than_seconds=older_than_seconds,
        confirm=confirm if confirm is not None else _default_confirm,
        now=now,
    )

    typer.echo("")
    if failures:
        typer.secho(
            f"{len(failures)} check(s) failed: {', '.join(failures)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    typer.secho("all checks passed", fg=typer.colors.GREEN)
