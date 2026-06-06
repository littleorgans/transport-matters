"""Desktop canvas launch glue.

The desktop command deliberately reuses the existing Claude and Codex
foreground launch paths. This module only validates the union CLI surface,
emits the canvas launch contract once the backend is ready, and starts the
detached Electron viewer.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import typer
from click.core import ParameterSource

from transport_matters import env_keys
from transport_matters.workspace import workspace_id

from .net import loopback_http_url

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from .launch_options import AgentName
    from .runner import ManagedClient

DESKTOP_APP_BIN_ENV = env_keys.DESKTOP_APP_BIN
DESKTOP_APP_DIR_ENV = env_keys.DESKTOP_APP_DIR
DESKTOP_ELECTRON_BIN_ENV = env_keys.DESKTOP_ELECTRON_BIN
DESKTOP_LAUNCH_CONTEXT_ENV = env_keys.DESKTOP_LAUNCH_CONTEXT
DESKTOP_ROUTE_URL_ENV = env_keys.DESKTOP_ROUTE_URL
DESKTOP_CLIENT_ENV = env_keys.DESKTOP_CLIENT

_CLAUDE_ONLY_OPTIONS = frozenset({"upstream", "claude_bin", "no_claude", "no_system_prompt"})
_CODEX_ONLY_OPTIONS = frozenset({"codex_bin", "no_codex", "force_http_fallback"})
_OPTION_LABELS = {
    "upstream": "--upstream",
    "claude_bin": "--claude-bin",
    "no_claude": "--no-claude",
    "no_system_prompt": "--no-system-prompt",
    "codex_bin": "--codex-bin",
    "no_codex": "--no-codex",
    "force_http_fallback": "--force-http-fallback",
}


@dataclass(frozen=True)
class ElectronLaunch:
    """Resolved command for the detached Electron viewer."""

    argv: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True)
class DesktopLaunchPlan:
    """Validated desktop command plan."""

    agent: AgentName
    run_client_with_retry: Callable[..., None]


class ElectronResolutionError(RuntimeError):
    """Raised when the Electron viewer cannot be resolved before launch."""


def prepare_desktop_launch(
    *,
    ctx: typer.Context,
    agent: AgentName,
    base_run_client_with_retry: Callable[..., None],
    launch_viewer: bool = True,
    resolve_electron_launch_func: Callable[[], ElectronLaunch] | None = None,
    spawn_electron_func: Callable[[ElectronLaunch, dict[str, Any]], None] | None = None,
) -> DesktopLaunchPlan:
    """Validate desktop options and wrap the launch retry hook."""
    normalized_agent = _normalize_agent(agent)
    _reject_irrelevant_options(ctx, normalized_agent)
    resolve_electron = resolve_electron_launch_func or resolve_electron_launch
    spawn_electron = spawn_electron_func or spawn_detached_electron
    electron_launch = _resolve_or_exit(resolve_electron) if launch_viewer else None

    def run_client_with_retry(**kwargs: Any) -> None:
        previous_hook = kwargs.pop("on_backend_ready", None)

        def on_backend_ready(
            launch_env: dict[str, str],
            resolved_storage: Path,
            client: ManagedClient | None,
            proxy_port: int,
            web_port: int,
        ) -> None:
            if previous_hook is not None:
                previous_hook(launch_env, resolved_storage, client, proxy_port, web_port)
            event = build_backend_started_event(
                agent=normalized_agent,
                launch_env=launch_env,
                resolved_storage=resolved_storage,
                proxy_port=proxy_port,
                web_port=web_port,
            )
            typer.echo(json.dumps(event, separators=(",", ":"), sort_keys=True))
            if electron_launch is not None:
                _spawn_or_exit(spawn_electron, electron_launch, event)

        kwargs["on_backend_ready"] = on_backend_ready
        base_run_client_with_retry(**kwargs)

    return DesktopLaunchPlan(
        agent=normalized_agent,
        run_client_with_retry=run_client_with_retry,
    )


def build_backend_started_event(
    *,
    agent: AgentName,
    launch_env: Mapping[str, str],
    resolved_storage: Path,
    proxy_port: int,
    web_port: int,
) -> dict[str, Any]:
    """Build the one-line startup JSON contract for the desktop canvas."""
    cwd = launch_env[env_keys.CWD]
    wid = workspace_id(Path(cwd))
    base_url = loopback_http_url(web_port)
    return {
        "type": "transport_matters.backend_started",
        "agent": agent,
        "cwd": cwd,
        "workspace": {
            "slug": wid.slug,
            "hash": wid.hash,
        },
        "runId": launch_env[env_keys.RUN_ID],
        "proxyPort": proxy_port,
        "webPort": web_port,
        "baseUrl": base_url,
        "routeUrl": f"{base_url}/canvas",
        "storageDir": str(resolved_storage),
        "homeDir": launch_env.get(env_keys.HOME_DIR),
    }


def spawn_detached_electron(launch: ElectronLaunch, event: dict[str, Any]) -> None:
    """Start the desktop shell as a detached viewer for an existing backend."""
    context_json = json.dumps(event, separators=(",", ":"), sort_keys=True)
    env = {
        **os.environ,
        DESKTOP_CLIENT_ENV: str(event["agent"]),
        DESKTOP_LAUNCH_CONTEXT_ENV: context_json,
        DESKTOP_ROUTE_URL_ENV: str(event["routeUrl"]),
        env_keys.CWD: str(event["cwd"]),
        env_keys.PROXY_PORT: str(event["proxyPort"]),
        env_keys.RUN_ID: str(event["runId"]),
        env_keys.STORAGE_DIR: str(event["storageDir"]),
        env_keys.WEB_PORT: str(event["webPort"]),
    }
    if event["homeDir"] is not None:
        env[env_keys.HOME_DIR] = str(event["homeDir"])

    try:
        subprocess.Popen(
            list(launch.argv),
            cwd=str(launch.cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        msg = f"could not launch Transport Matters desktop viewer: {exc}"
        raise ElectronResolutionError(msg) from exc


def resolve_electron_launch(
    *,
    env: Mapping[str, str] = os.environ,
    which: Callable[[str], str | None] = shutil.which,
) -> ElectronLaunch:
    """Resolve the packaged Electron viewer or local development shell."""
    app_bin = _path_from_env(env, DESKTOP_APP_BIN_ENV)
    if app_bin is not None:
        _require_file(app_bin, DESKTOP_APP_BIN_ENV)
        return ElectronLaunch(argv=(str(app_bin),), cwd=app_bin.parent)

    app_dir = _resolve_desktop_app_dir(env)
    packaged = _packaged_app_binary(app_dir)
    if packaged is not None:
        return ElectronLaunch(argv=(str(packaged),), cwd=packaged.parent)

    electron_bin = _resolve_electron_binary(app_dir, env, which)
    if electron_bin is None:
        raise ElectronResolutionError(
            "could not locate Electron. Run `cd desktop && pnpm install && pnpm build`, "
            f"or set {DESKTOP_ELECTRON_BIN_ENV}."
        )
    return ElectronLaunch(argv=(str(electron_bin), str(app_dir)), cwd=app_dir)


def _normalize_agent(agent: AgentName) -> AgentName:
    normalized = agent.lower()
    if normalized not in {"claude", "codex"}:
        msg = f"unsupported desktop agent: {agent}"
        raise typer.BadParameter(msg)
    return cast("AgentName", normalized)


def _reject_irrelevant_options(ctx: typer.Context, agent: AgentName) -> None:
    rejected = _CODEX_ONLY_OPTIONS if agent == "claude" else _CLAUDE_ONLY_OPTIONS
    supplied = [_OPTION_LABELS[name] for name in sorted(rejected) if _option_supplied(ctx, name)]
    if not supplied:
        return
    valid_agent = "codex" if agent == "claude" else "claude"
    option_list = ", ".join(supplied)
    typer.secho(
        f"error: {option_list} only valid with --agent {valid_agent}.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(2)


def _option_supplied(ctx: typer.Context, name: str) -> bool:
    source = ctx.get_parameter_source(name)
    return source in {ParameterSource.COMMANDLINE, ParameterSource.ENVIRONMENT}


def _resolve_or_exit(resolve_electron_launch: Callable[[], ElectronLaunch]) -> ElectronLaunch:
    try:
        return resolve_electron_launch()
    except ElectronResolutionError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


def _spawn_or_exit(
    spawn_electron: Callable[[ElectronLaunch, dict[str, Any]], None],
    launch: ElectronLaunch,
    event: dict[str, Any],
) -> None:
    try:
        spawn_electron(launch, event)
    except ElectronResolutionError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


def _resolve_desktop_app_dir(env: Mapping[str, str]) -> Path:
    override = _path_from_env(env, DESKTOP_APP_DIR_ENV)
    if override is not None:
        _require_desktop_app_dir(override, DESKTOP_APP_DIR_ENV)
        return override

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "desktop"
        if _is_desktop_app_dir(candidate):
            return candidate

    raise ElectronResolutionError(
        "could not locate the desktop app directory. Run from the repository checkout, "
        f"or set {DESKTOP_APP_DIR_ENV}."
    )


def _resolve_electron_binary(
    app_dir: Path,
    env: Mapping[str, str],
    which: Callable[[str], str | None],
) -> Path | None:
    override = _path_from_env(env, DESKTOP_ELECTRON_BIN_ENV)
    if override is not None:
        _require_file(override, DESKTOP_ELECTRON_BIN_ENV)
        return override

    local = app_dir / "node_modules" / ".bin" / "electron"
    if local.is_file():
        return local
    found = which("electron")
    return Path(found) if found is not None else None


def _packaged_app_binary(app_dir: Path) -> Path | None:
    patterns = (
        "dist/package-smoke/**/Transport Matters.app/Contents/MacOS/Transport Matters",
        "dist/package-smoke/**/Transport Matters",
        "dist/package-smoke/**/transport-matters-desktop",
    )
    for pattern in patterns:
        matches = sorted(app_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def _path_from_env(env: Mapping[str, str], key: str) -> Path | None:
    raw = env.get(key)
    if raw is None:
        return None
    return Path(raw).expanduser().resolve()


def _require_desktop_app_dir(path: Path, env_key: str) -> None:
    if not _is_desktop_app_dir(path):
        raise ElectronResolutionError(
            f"{env_key} must point at a built desktop app directory with package.json "
            "and dist/main.js."
        )


def _is_desktop_app_dir(path: Path) -> bool:
    return (path / "package.json").is_file() and (path / "dist" / "main.js").is_file()


def _require_file(path: Path, env_key: str) -> None:
    if not path.is_file():
        raise ElectronResolutionError(f"{env_key} must point at an executable file: {path}")
