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
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode

import typer

from transport_matters import env_keys
from transport_matters.channel import ChannelSpec, activate_channel, resolve_channel_spec
from transport_matters.storage_roots import default_storage_root
from transport_matters.workspace import workspace_id

from .desktop_runtime import (
    DesktopRuntimeRecord,
    desktop_log_path,
    desktop_record_path,
    write_desktop_record,
)
from .launch_runtime import preflight_session_store_or_exit
from .net import (
    LOOPBACK_HOST,
    loopback_http_url,
    port_in_use,
    raise_port_in_use,
    wait_for_port_ready,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

RouteName = Literal["canvas", "canvas-lab"]

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
    env_keys.HARNESS,
    env_keys.DEFAULT_CLIENT_PASSTHROUGH,
    env_keys.LAUNCH_FIELDS,
    env_keys.OWNED_NATIVE_SESSION_ID,
    env_keys.OWNED_SOURCE_DESCRIPTOR,
    env_keys.RESUME_CONTEXT,
    env_keys.RUN_ID,
)


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
    channel: str | None = None,
    route: RouteName = "canvas",
    work_dir: Path | None = None,
    proxy_port: int | None = None,
    web_port: int | None = None,
    storage_dir: Path | None = None,
    debug: bool = False,
    env: Mapping[str, str] | None = None,
    allocate_port_pair_func: Callable[[], tuple[int, int]] | None = None,
    port_in_use_func: Callable[[int], bool] = port_in_use,
    launch_viewer: bool = True,
    resolve_electron_launch_func: Callable[[], ElectronLaunch] | None = None,
) -> DesktopLaunchPlan:
    """Resolve the backend server launch used by the desktop shell."""
    source_env = os.environ if env is None else env
    channel_spec = resolve_channel_spec(channel, source_env)
    normalized_route = _normalize_route(route)
    resolved_proxy_port, resolved_web_port = _resolve_backend_ports(
        proxy_port,
        web_port,
        channel_spec=channel_spec,
        allocate_port_pair_func=allocate_port_pair_func,
        port_in_use_func=port_in_use_func,
    )
    resolved_cwd = _resolve_work_dir(work_dir)
    resolved_storage = _resolve_storage_dir(storage_dir, channel=channel_spec.id, env=source_env)
    launch_env = _build_desktop_backend_env(
        cwd=resolved_cwd,
        storage_dir=resolved_storage,
        proxy_port=resolved_proxy_port,
        web_port=resolved_web_port,
        channel=channel_spec.id,
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
            channel=channel_spec.id,
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
    channel: str | None = None,
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
    activate_channel(channel)
    plan = prepare_desktop_launch(
        channel=channel,
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


def run_desktop_detached(
    *,
    channel: str | None = None,
    route: RouteName = "canvas",
    work_dir: Path | None = None,
    proxy_port: int | None = None,
    web_port: int | None = None,
    storage_dir: Path | None = None,
    debug: bool = False,
    allocate_port_pair_func: Callable[[], tuple[int, int]] | None = None,
    resolve_electron_launch_func: Callable[[], ElectronLaunch] | None = None,
    spawn_electron_func: Callable[[ElectronLaunch, dict[str, Any]], None] | None = None,
    popen_func: Callable[..., Any] | None = None,
) -> None:
    """Start the desktop backend detached, open the viewer, and return."""
    channel_spec = activate_channel(channel)
    plan = prepare_desktop_launch(
        channel=channel_spec.id,
        route=route,
        work_dir=work_dir,
        proxy_port=proxy_port,
        web_port=web_port,
        storage_dir=storage_dir,
        debug=debug,
        allocate_port_pair_func=allocate_port_pair_func,
        launch_viewer=True,
        resolve_electron_launch_func=resolve_electron_launch_func,
    )
    resolved_cwd = Path(plan.env[env_keys.CWD])
    resolved_storage = Path(plan.event["storageDir"])
    log_path = desktop_log_path(resolved_storage)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    popen = popen_func or subprocess.Popen
    with log_path.open("ab") as log_handle:
        process = popen(
            list(plan.command),
            cwd=str(resolved_cwd),
            env=plan.env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )

    record = DesktopRuntimeRecord(
        channel=channel_spec.id,
        pid=int(process.pid),
        proxy_port=int(plan.env[env_keys.PROXY_PORT]),
        web_port=plan.web_port,
        log_path=str(log_path),
    )
    write_desktop_record(desktop_record_path(resolved_storage), record)

    if plan.electron_launch is not None:
        spawn_electron = spawn_electron_func or spawn_detached_electron
        _spawn_or_exit(spawn_electron, plan.electron_launch, plan.event)


def run_desktop_backend_server(
    *,
    channel: str | None = None,
    work_dir: Path | None = None,
    proxy_port: int | None = None,
    web_port: int | None = None,
    storage_dir: Path | None = None,
    debug: bool = False,
    allocate_port_pair_func: Callable[[], tuple[int, int]] | None = None,
) -> None:
    """Run only the desktop backend server for the Electron owned child path."""
    activate_channel(channel)
    plan = prepare_desktop_launch(
        channel=channel,
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
    channel_spec: ChannelSpec,
    allocate_port_pair_func: Callable[[], tuple[int, int]] | None = None,
    port_in_use_func: Callable[[int], bool] = port_in_use,
) -> tuple[int, int]:
    if allocate_port_pair_func is None:
        default_proxy_port = channel_spec.proxy_port
        default_web_port = channel_spec.web_port
    else:
        default_proxy_port, default_web_port = allocate_port_pair_func()
    resolved_proxy_port = proxy_port if proxy_port is not None else default_proxy_port
    resolved_web_port = web_port if web_port is not None else default_web_port
    for label, flag, port in (
        ("proxy", "--proxy-port", resolved_proxy_port),
        ("web UI", "--web-port", resolved_web_port),
    ):
        if port_in_use_func(port):
            raise_port_in_use(label, flag, port)
    return resolved_proxy_port, resolved_web_port


def _resolve_work_dir(work_dir: Path | None) -> Path:
    resolved = (work_dir if work_dir is not None else Path.cwd()).expanduser().resolve()
    if not resolved.exists():
        msg = f"work directory does not exist: {resolved}"
        raise typer.BadParameter(msg)
    if not resolved.is_dir():
        msg = f"work directory is not a directory: {resolved}"
        raise typer.BadParameter(msg)
    return resolved


def _resolve_storage_dir(
    storage_dir: Path | None,
    *,
    channel: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    return (
        (storage_dir if storage_dir is not None else default_storage_root(channel, env=env))
        .expanduser()
        .resolve()
    )


def _build_desktop_backend_env(
    *,
    cwd: Path,
    storage_dir: Path,
    proxy_port: int,
    web_port: int,
    channel: str,
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
    backend_env[env_keys.CHANNEL] = channel
    if debug:
        backend_env[DEBUG_ENV] = "1"
    return backend_env


def _build_desktop_backend_command(
    *,
    work_dir: Path,
    storage_dir: Path,
    proxy_port: int,
    web_port: int,
    channel: str,
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
        "--channel",
        channel,
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


def _normalize_route(route: str) -> str:
    normalized = route.lower()
    if normalized not in {"canvas", "canvas-lab"}:
        msg = f"unsupported desktop route: {route}"
        raise typer.BadParameter(msg)
    return normalized


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
