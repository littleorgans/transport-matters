"""Body of the ``transport-matters doctor`` subcommand.

Split out from :mod:`transport_matters.cli` so the package entry point stays
under the 700-LOC invariant. The typer command itself stays in
``cli/__init__.py`` as a thin wrapper that calls :func:`run_doctor`.

Tests that previously patched ``transport_matters.cli.shutil.which`` /
``transport_matters.cli._port_in_use`` continue to work because those
re-exports are still resolved at call time inside ``run_doctor``'s own module.
"""

from __future__ import annotations

import shutil
import sys
import sysconfig
from importlib.resources import files
from pathlib import Path

import typer

from transport_matters import __version__
from transport_matters.config import get_settings

from .identity import CLI_COMMAND, PRODUCT_LABEL
from .launch_runtime import resolve_mitmdump_executable
from .net import _port_in_use

__all__ = ["run_doctor"]


def run_doctor() -> None:
    """Run the diagnostic checklist and exit non-zero on any failure.

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
        if _port_in_use(port):
            typer.secho(
                f"  warn  {label} {port} in use — "
                f"pick a different port with --{label.split()[0]}-port",
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
