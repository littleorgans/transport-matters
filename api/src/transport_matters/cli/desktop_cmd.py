"""Desktop canvas launch glue."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlencode

import typer
from click.core import ParameterSource

from transport_matters import env_keys
from transport_matters.storage_roots import default_storage_root
from transport_matters.workspace import workspace_id

from .launch_runtime import preflight_session_store_or_exit
from .net import LOOPBACK_HOST, loopback_http_url, wait_for_port_ready

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from .launch_options import AgentName, RouteName

DESKTOP_APP_BIN_ENV = env_keys.DESKTOP_APP_BIN
DESKTOP_APP_DIR_ENV = env_keys.DESKTOP_APP_DIR
DESKTOP_ELECTRON_BIN_ENV = env_keys.DESKTOP_ELECTRON_BIN
DESKTOP_ROUTE_URL_ENV = env_keys.DESKTOP_ROUTE_URL
DESKTOP_CLIENT_ENV = env_keys.DESKTOP_CLIENT
DESKTOP_BACKEND_COMMAND = "_desktop-backend"
DEBUG_ENV = f"{env_keys.ENV_PREFIX}DEBUG"
_BACKEND_READY_TIMEOUT_S = 15.0
_DESKTOP_BACKEND_STALE_ENV_KEYS = (
    DESKTOP_CLIENT_ENV,
    DESKTOP_ROUTE_URL_ENV,
    env_keys.AGENT_HOME_DIR,
    env_keys.CLI,
    env_keys.DEFAULT_CLIENT_PASSTHROUGH,
    env_keys.LAUNCH_FIELDS,
    env_keys.OWNED_NATIVE_SESSION_ID,
    env_keys.OWNED_SOURCE_DESCRIPTOR,
    env_keys.RESUME_CONTEXT,
    env_keys.RUN_ID,
)

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
    """Resolved desktop backend launch plan."""

    command: tuple[str, ...]
    electron_launch: ElectronLaunch | None
    env: dict[str, str]
    event: dict[str, Any]
    web_port: int


class ElectronResolutionError(RuntimeError):
    """Raised when the Electron viewer cannot be resolved before launch."""


class DesktopBackendStartError(RuntimeError):
    """Raised when the desktop backend does not become reachable."""


def prepare_desktop_launch(
    *,
    route: RouteName = "canvas",
    work_dir: Path | None = None,
    proxy_port: int | None = None,
    web_port: int | None = None,
    storage_dir: Path | None = None,
    debug: bool = False,
    env: Mapping[str, str] | None = None,
    allocate_port_pair_func: Callable[[], tuple[int, int]] | None = None,
    launch_viewer: bool = True,
    resolve_electron_launch_func: Callable[[], ElectronLaunch] | None = None,
) -> DesktopLaunchPlan:
    """Resolve the backend server launch used by the desktop shell."""
    normalized_route = _normalize_route(route)
    resolved_proxy_port, resolved_web_port = _resolve_backend_ports(
        proxy_port,
        web_port,
        allocate_port_pair_func=allocate_port_pair_func,
    )
    resolved_cwd = _resolve_work_dir(work_dir)
    resolved_storage = _resolve_storage_dir(storage_dir)
    launch_env = _build_desktop_backend_env(
        cwd=resolved_cwd,
        storage_dir=resolved_storage,
        proxy_port=resolved_proxy_port,
        web_port=resolved_web_port,
        debug=debug,
        env=env,
    )
    event = build_backend_started_event(
        route=normalized_route,
        cwd=resolved_cwd,
        resolved_storage=resolved_storage,
        web_port=resolved_web_port,
    )
    resolve_electron = resolve_electron_launch_func or resolve_electron_launch
    electron_launch = _resolve_or_exit(resolve_electron) if launch_viewer else None
    return DesktopLaunchPlan(
        command=_build_desktop_backend_command(
            work_dir=resolved_cwd,
            storage_dir=resolved_storage,
            proxy_port=resolved_proxy_port,
            web_port=resolved_web_port,
            debug=debug,
        ),
        electron_launch=electron_launch,
        env=launch_env,
        event=event,
        web_port=resolved_web_port,
    )


def build_backend_started_event(
    *,
    route: str,
    cwd: Path,
    resolved_storage: Path,
    web_port: int,
) -> dict[str, Any]:
    """Build the one-line startup JSON contract for the desktop canvas."""
    wid = workspace_id(cwd)
    base_url = loopback_http_url(web_port)
    route_query = urlencode(
        {
            "owner": "local",
            "workspace_hash": wid.hash,
        }
    )
    return {
        "type": "transport_matters.backend_started",
        "cwd": str(cwd),
        "workspace": {
            "slug": wid.slug,
            "hash": wid.hash,
        },
        "webPort": web_port,
        "baseUrl": base_url,
        "routeUrl": f"{base_url}/{route}?{route_query}",
        "storageDir": str(resolved_storage),
    }


def spawn_detached_electron(launch: ElectronLaunch, event: dict[str, Any]) -> None:
    """Start the desktop shell as a detached viewer for an existing backend."""
    env = {
        **os.environ,
        DESKTOP_ROUTE_URL_ENV: str(event["routeUrl"]),
        env_keys.CWD: str(event["cwd"]),
        env_keys.STORAGE_DIR: str(event["storageDir"]),
        env_keys.WEB_PORT: str(event["webPort"]),
    }

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


def run_desktop_launch(
    *,
    route: RouteName = "canvas",
    work_dir: Path | None = None,
    proxy_port: int | None = None,
    web_port: int | None = None,
    storage_dir: Path | None = None,
    debug: bool = False,
    print_command: bool = False,
    allocate_port_pair_func: Callable[[], tuple[int, int]] | None = None,
    resolve_electron_launch_func: Callable[[], ElectronLaunch] | None = None,
    spawn_electron_func: Callable[[ElectronLaunch, dict[str, Any]], None] | None = None,
    serve_backend_func: Callable[[DesktopLaunchPlan, Callable[[], None] | None], None]
    | None = None,
) -> None:
    """Run the desktop backend server and open the hosted Electron viewer."""
    plan = prepare_desktop_launch(
        route=route,
        work_dir=work_dir,
        proxy_port=proxy_port,
        web_port=web_port,
        storage_dir=storage_dir,
        debug=debug,
        allocate_port_pair_func=allocate_port_pair_func,
        launch_viewer=not print_command,
        resolve_electron_launch_func=resolve_electron_launch_func,
    )
    if print_command:
        typer.echo(shlex.join(plan.command))
        return

    spawn_electron = spawn_electron_func or spawn_detached_electron
    serve_backend = serve_backend_func or serve_desktop_backend

    def on_backend_ready() -> None:
        typer.echo(json.dumps(plan.event, separators=(",", ":"), sort_keys=True))
        if plan.electron_launch is not None:
            _spawn_or_exit(spawn_electron, plan.electron_launch, plan.event)

    serve_backend(plan, on_backend_ready)


def run_desktop_backend_server(
    *,
    work_dir: Path | None = None,
    proxy_port: int | None = None,
    web_port: int | None = None,
    storage_dir: Path | None = None,
    debug: bool = False,
    allocate_port_pair_func: Callable[[], tuple[int, int]] | None = None,
) -> None:
    """Run only the desktop backend server for the Electron owned child path."""
    plan = prepare_desktop_launch(
        work_dir=work_dir,
        proxy_port=proxy_port,
        web_port=web_port,
        storage_dir=storage_dir,
        debug=debug,
        allocate_port_pair_func=allocate_port_pair_func,
        launch_viewer=False,
    )
    serve_desktop_backend(plan, None)


def serve_desktop_backend(
    plan: DesktopLaunchPlan,
    on_backend_ready: Callable[[], None] | None = None,
) -> None:
    """Serve the desktop backend, optionally notifying after readiness."""
    _apply_desktop_backend_env(plan.env)
    preflight_session_store_or_exit()

    import uvicorn

    from transport_matters.config import get_settings
    from transport_matters.main import LOG_CONFIG, create_app

    get_settings.cache_clear()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(),
            host=LOOPBACK_HOST,
            port=plan.web_port,
            log_config=LOG_CONFIG,
        )
    )
    if on_backend_ready is None:
        server.run()
        return

    thread = Thread(target=server.run, name="transport-matters-desktop-backend", daemon=True)
    thread.start()
    try:
        if not wait_for_port_ready(
            LOOPBACK_HOST,
            plan.web_port,
            timeout=_BACKEND_READY_TIMEOUT_S,
        ):
            server.should_exit = True
            msg = f"desktop backend did not become ready on {loopback_http_url(plan.web_port)}"
            raise DesktopBackendStartError(msg)
        try:
            on_backend_ready()
        except Exception:
            server.should_exit = True
            raise
        thread.join()
    except KeyboardInterrupt:
        server.should_exit = True
        raise
    finally:
        if server.should_exit and thread.is_alive():
            thread.join(timeout=5.0)


def _resolve_backend_ports(
    proxy_port: int | None,
    web_port: int | None,
    *,
    allocate_port_pair_func: Callable[[], tuple[int, int]] | None = None,
) -> tuple[int, int]:
    if proxy_port is not None and web_port is not None:
        return proxy_port, web_port
    allocate = allocate_port_pair_func or _allocate_port_pair
    allocated_proxy_port, allocated_web_port = allocate()
    return proxy_port or allocated_proxy_port, web_port or allocated_web_port


def _allocate_port_pair() -> tuple[int, int]:
    from .ports import allocate_port_pair

    return allocate_port_pair()


def _resolve_work_dir(work_dir: Path | None) -> Path:
    resolved = (work_dir if work_dir is not None else Path.cwd()).expanduser().resolve()
    if not resolved.exists():
        msg = f"work directory does not exist: {resolved}"
        raise typer.BadParameter(msg)
    if not resolved.is_dir():
        msg = f"work directory is not a directory: {resolved}"
        raise typer.BadParameter(msg)
    return resolved


def _resolve_storage_dir(storage_dir: Path | None) -> Path:
    return (
        (storage_dir if storage_dir is not None else default_storage_root()).expanduser().resolve()
    )


def _build_desktop_backend_env(
    *,
    cwd: Path,
    storage_dir: Path,
    proxy_port: int,
    web_port: int,
    debug: bool,
    env: Mapping[str, str] | None,
) -> dict[str, str]:
    backend_env = dict(os.environ if env is None else env)
    for key in _DESKTOP_BACKEND_STALE_ENV_KEYS:
        backend_env.pop(key, None)
    backend_env[env_keys.CWD] = str(cwd)
    backend_env[env_keys.PROXY_PORT] = str(proxy_port)
    backend_env[env_keys.STORAGE_DIR] = str(storage_dir)
    backend_env[env_keys.WEB_PORT] = str(web_port)
    if debug:
        backend_env[DEBUG_ENV] = "1"
    return backend_env


def _build_desktop_backend_command(
    *,
    work_dir: Path,
    storage_dir: Path,
    proxy_port: int,
    web_port: int,
    debug: bool,
) -> tuple[str, ...]:
    command = [
        "transport-matters",
        DESKTOP_BACKEND_COMMAND,
        "--work-dir",
        str(work_dir),
        "--web-port",
        str(web_port),
        "--proxy-port",
        str(proxy_port),
        "--storage-dir",
        str(storage_dir),
    ]
    if debug:
        command.append("--debug")
    return tuple(command)


def _apply_desktop_backend_env(env: Mapping[str, str]) -> None:
    for key in _DESKTOP_BACKEND_STALE_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.update(env)


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


def _normalize_route(route: str) -> str:
    normalized = route.lower()
    if normalized not in {"canvas", "canvas-lab"}:
        msg = f"unsupported desktop route: {route}"
        raise typer.BadParameter(msg)
    return normalized


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
    return source == ParameterSource.COMMANDLINE


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
