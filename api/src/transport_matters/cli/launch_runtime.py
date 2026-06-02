"""Shared launch plumbing for the CLI entrypoints."""

from __future__ import annotations

import contextlib
import os
import shutil
import sysconfig
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import typer

from transport_matters import __version__
from transport_matters.lock import WorkspaceLock
from transport_matters.manifest import Manifest
from transport_matters.manifest import write as manifest_write
from transport_matters.workspace import run_root, workspace_id

from .identity import CLI_COMMAND, PRODUCT_LABEL
from .ports import PortAllocationError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from importlib.resources.abc import Traversable

    from .runner import ManagedClient


class WhichFunction(Protocol):
    def __call__(
        self,
        cmd: str,
        mode: int = ...,
        path: str | None = ...,
    ) -> str | None: ...


@dataclass(frozen=True)
class LaunchPreparation:
    addon_traversable: Traversable
    mitmdump: str
    client_path: str | None
    working_dir: Path
    proxy_port: int
    web_port: int
    proxy_user_supplied: bool
    web_user_supplied: bool
    run_id: str
    resolved_storage: Path
    passthrough_user: tuple[str, ...]


_MANAGED_CHILD_PROXY_ENV_KEYS = frozenset(
    {
        "ALL_PROXY",
        "all_proxy",
        "BUNDLE_HTTP_PROXY",
        "BUNDLE_HTTPS_PROXY",
        "BUNDLE_NO_PROXY",
        "DOCKER_HTTP_PROXY",
        "DOCKER_HTTPS_PROXY",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
        "FTP_PROXY",
        "ftp_proxy",
        "WS_PROXY",
        "ws_proxy",
        "WSS_PROXY",
        "wss_proxy",
        "npm_config_proxy",
        "NPM_CONFIG_PROXY",
        "npm_config_http_proxy",
        "NPM_CONFIG_HTTP_PROXY",
        "npm_config_https_proxy",
        "NPM_CONFIG_HTTPS_PROXY",
        "npm_config_noproxy",
        "NPM_CONFIG_NOPROXY",
        "npm_config_no_proxy",
        "NPM_CONFIG_NO_PROXY",
        "PIP_PROXY",
        "YARN_HTTP_PROXY",
        "YARN_HTTPS_PROXY",
        "YARN_NO_PROXY",
    }
)

_MANAGED_CHILD_PROXY_INTERNAL_ENV_KEYS = frozenset(
    {
        "CODEX_NETWORK_ALLOW_LOCAL_BINDING",
        "CODEX_NETWORK_PROXY_ACTIVE",
        "ELECTRON_GET_USE_PROXY",
    }
)

_MANAGED_CHILD_TRUST_ENV_KEYS = frozenset(
    {
        "CODEX_CA_CERTIFICATE",
        "CURL_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "NODE_TLS_REJECT_UNAUTHORIZED",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "npm_config_cafile",
        "NPM_CONFIG_CAFILE",
    }
)

_LOOPBACK_NO_PROXY = "127.0.0.1,localhost"

CLIENT_NAME_CLAUDE = "claude"
CLIENT_NAME_CODEX = "codex"

_HOME_DIR_ENV_BY_CLIENT = {
    CLIENT_NAME_CLAUDE: "CLAUDE_CONFIG_DIR",
    CLIENT_NAME_CODEX: "CODEX_HOME",
}


def _candidate_has_missing_shebang_interpreter(candidate: Path) -> bool:
    try:
        first_line = candidate.open("rb").readline(4096)
    except OSError:
        return True
    if not first_line.startswith(b"#!"):
        return False

    shebang = first_line[2:].decode("utf-8", "ignore").strip()
    if not shebang:
        return True

    interpreter = shebang.split(maxsplit=1)[0]
    if interpreter == "/usr/bin/env":
        return False
    if interpreter.startswith("/"):
        return not Path(interpreter).exists()
    return False


def _candidate_is_runnable(candidate: str) -> bool:
    path = Path(candidate)
    if not path.exists():
        # Real shutil.which only returns existing executables; tests inject
        # synthetic paths through the same resolver hook.
        return True
    if not path.is_file():
        return False
    if not os.access(path, os.X_OK):
        return False
    return not _candidate_has_missing_shebang_interpreter(path)


def _which_runnable(
    name: str,
    *,
    which: WhichFunction,
    path: str | None = None,
) -> str | None:
    search_dirs = path.split(os.pathsep) if path is not None else os.get_exec_path()
    seen: set[str] = set()
    for directory in search_dirs:
        resolved = which(name, path=directory)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        if _candidate_is_runnable(resolved):
            return resolved
    return None


def resolve_client_binary(
    *,
    name: str,
    bin_override: Path | None,
    disabled: bool,
    which: Callable[[str], str | None],
    not_found_hint: str,
) -> str | None:
    """Resolve a managed client binary or exit with caller-specific guidance."""
    if disabled:
        return None

    client_path = str(bin_override) if bin_override is not None else which(name)
    if client_path is not None:
        return client_path

    typer.secho(
        f"error: `{name}` was not found on PATH.",
        fg=typer.colors.RED,
        err=True,
    )
    typer.echo(not_found_hint, err=True)
    raise typer.Exit(2)


def resolve_mitmdump_executable(
    *,
    which: WhichFunction = shutil.which,
    get_scripts_dir: Callable[[str], str | None] = sysconfig.get_path,
) -> str | None:
    """Resolve a mitmdump executable that the kernel can actually run."""
    scripts_dir = get_scripts_dir("scripts")
    if scripts_dir:
        resolved = _which_runnable("mitmdump", which=which, path=scripts_dir)
        if resolved is not None:
            return resolved
    return _which_runnable("mitmdump", which=which)


def reject_passthrough_without_client(
    *,
    disabled: bool,
    passthrough: Sequence[str],
    flag: str,
) -> None:
    """Fail fast when pass-through args exist but no client will be spawned."""
    if disabled and passthrough:
        typer.secho(
            f"error: {flag} is incompatible with pass-through args after '--'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)


def resolve_working_dir(directory: Path | None) -> Path:
    """Resolve the effective working directory and validate it exists."""
    working_dir = directory if directory is not None else Path.cwd()
    if not working_dir.is_dir():
        typer.secho(
            f"error: directory does not exist: {working_dir}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    return working_dir


def resolve_launch_ports(
    *,
    proxy_port: int | None,
    web_port: int | None,
    port_in_use: Callable[[int], bool],
    allocate_port_pair: Callable[[], tuple[int, int]],
) -> tuple[int, int, bool, bool]:
    """Resolve the proxy and web ports, preserving which ones were pinned."""
    proxy_user_supplied = proxy_port is not None
    web_user_supplied = web_port is not None

    if proxy_port is None or web_port is None:
        try:
            allocated_proxy, allocated_web = allocate_port_pair()
        except PortAllocationError as exc:
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc
        if proxy_port is None:
            proxy_port = allocated_proxy
        if web_port is None:
            web_port = allocated_web

    for label, flag, port, pinned in (
        ("proxy", "--proxy-port", proxy_port, proxy_user_supplied),
        ("web UI", "--web-port", web_port, web_user_supplied),
    ):
        if pinned and port_in_use(port):
            typer.secho(
                f"error: {label} port {port} is already in use.",
                fg=typer.colors.RED,
                err=True,
            )
            typer.echo(
                "Another process is already bound to this port. Either stop it,\n"
                f"or pick a different port (omit {flag} to let "
                f"{PRODUCT_LABEL} allocate one).",
                err=True,
            )
            raise typer.Exit(2)

    return proxy_port, web_port, proxy_user_supplied, web_user_supplied


def resolve_storage_dir(*, storage_dir: Path | None, working_dir: Path, run_id: str) -> Path:
    """Resolve the storage root path for the launch without creating it.

    An explicit ``--storage-dir`` is caller-owned and used verbatim. The
    default is the per-run directory ``{slug}/{hash}/{run_id}/``, so two
    instances launched from the same CWD get isolated storage roots. Real
    launches create the default path when the per-run lock is acquired;
    ``--print-command`` only needs the path string and must not mint an empty
    run directory.
    """
    if storage_dir is not None:
        return storage_dir
    return run_root(working_dir, run_id)


def resolve_mitmdump_or_exit(
    *,
    resolve_mitmdump: Callable[[], str | None],
) -> str:
    """Resolve mitmdump from the current environment or exit with guidance."""
    mitmdump = resolve_mitmdump()
    if mitmdump is not None:
        return mitmdump

    typer.secho(
        "error: `mitmdump` was not found on PATH.",
        fg=typer.colors.RED,
        err=True,
    )
    typer.echo(
        f"mitmproxy ships as a runtime dependency of {PRODUCT_LABEL}, so this\n"
        "usually means the install did not link the console scripts.\n"
        "\n"
        "Try one of:\n"
        f"  uv tool install --force {CLI_COMMAND}     # reinstall as a tool\n"
        f"  pipx reinstall {CLI_COMMAND}              # if you used pipx\n"
        f"  pip install --force-reinstall {CLI_COMMAND}",
        err=True,
    )
    raise typer.Exit(2)


def new_run_id() -> str:
    """Return a fresh run identifier for the current launch."""
    return str(uuid.uuid4())


def prepare_launch(
    *,
    passthrough: list[str],
    directory: Path | None,
    proxy_port: int | None,
    web_port: int | None,
    storage_dir: Path | None,
    client_name: str,
    bin_override: Path | None,
    client_disabled: bool,
    not_found_hint: str,
    require_addon: Callable[[], Traversable],
    resolve_mitmdump: Callable[[], str | None],
    which: Callable[[str], str | None],
    port_in_use: Callable[[int], bool],
    allocate_port_pair: Callable[[], tuple[int, int]],
    validate_after_client_resolution: Callable[[], None] | None = None,
) -> LaunchPreparation:
    """Resolve the shared launch state in the legacy command order."""
    addon_traversable = require_addon()
    mitmdump = resolve_mitmdump_or_exit(resolve_mitmdump=resolve_mitmdump)
    client_path = resolve_client_binary(
        name=client_name,
        bin_override=bin_override,
        disabled=client_disabled,
        which=which,
        not_found_hint=not_found_hint,
    )
    if validate_after_client_resolution is not None:
        validate_after_client_resolution()

    working_dir = resolve_working_dir(directory)
    (
        resolved_proxy_port,
        resolved_web_port,
        proxy_user_supplied,
        web_user_supplied,
    ) = resolve_launch_ports(
        proxy_port=proxy_port,
        web_port=web_port,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
    )
    run_id = new_run_id()
    resolved_storage = resolve_storage_dir(
        storage_dir=storage_dir,
        working_dir=working_dir,
        run_id=run_id,
    )

    return LaunchPreparation(
        addon_traversable=addon_traversable,
        mitmdump=mitmdump,
        client_path=client_path,
        working_dir=working_dir,
        proxy_port=resolved_proxy_port,
        web_port=resolved_web_port,
        proxy_user_supplied=proxy_user_supplied,
        web_user_supplied=web_user_supplied,
        run_id=run_id,
        resolved_storage=resolved_storage,
        passthrough_user=tuple(passthrough),
    )


def build_mitmdump_argv(
    *,
    mitmdump: str,
    mode: str,
    proxy_port: int,
    addon_path: Path,
    debug: bool,
    extra_addons: Sequence[Path] = (),
) -> list[str]:
    argv = [
        mitmdump,
        "--mode",
        mode,
        "--listen-host",
        "127.0.0.1",
        "--listen-port",
        str(proxy_port),
        "-s",
        str(addon_path),
    ]
    for extra_addon in extra_addons:
        argv.extend(["-s", str(extra_addon)])
    if not debug:
        argv.extend(["--set", "termlog_verbosity=warn"])
    return argv


def print_invocation(
    *,
    build_invocation: Callable[[int, int], tuple[list[str], dict[str, str], ManagedClient | None]],
    proxy_port: int,
    web_port: int,
) -> None:
    mitmdump_argv, _env, client = build_invocation(proxy_port, web_port)
    typer.echo(" ".join(mitmdump_argv))
    if client is not None:
        typer.echo(" ".join(client.argv))
    raise typer.Exit(0)


def managed_child_shell_env_excludes() -> tuple[str, ...]:
    """Return managed env keys that nested tool shells should not inherit."""
    return tuple(sorted(_MANAGED_CHILD_PROXY_ENV_KEYS | _MANAGED_CHILD_TRUST_ENV_KEYS))


def build_launch_env(
    *,
    working_dir: Path,
    storage_dir: Path,
    proxy_port: int,
    web_port: int,
    run_id: str,
) -> dict[str, str]:
    """Return the shared runtime environment for a launch attempt."""
    env = os.environ.copy()
    env["TRANSPORT_MATTERS_STORAGE_DIR"] = str(storage_dir)
    env["TRANSPORT_MATTERS_WEB_PORT"] = str(web_port)
    env["TRANSPORT_MATTERS_PROXY_PORT"] = str(proxy_port)
    env["TRANSPORT_MATTERS_RUN_ID"] = run_id
    env["TRANSPORT_MATTERS_CWD"] = str(working_dir)
    return env


def build_managed_child_env(
    base_env: Mapping[str, str],
    *,
    client_name: str | None = None,
    home_dir: Path | None = None,
    proxy_url: str | None = None,
    codex_ca_certificate: str | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a deterministic child env that cannot bypass proxy or trust."""
    env = dict(base_env)
    for key in (
        _MANAGED_CHILD_PROXY_ENV_KEYS
        | _MANAGED_CHILD_PROXY_INTERNAL_ENV_KEYS
        | _MANAGED_CHILD_TRUST_ENV_KEYS
    ):
        env.pop(key, None)

    if proxy_url is not None:
        # Codex uses this marker to strip managed proxy vars from user commands.
        env["CODEX_NETWORK_PROXY_ACTIVE"] = "1"
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
        env["ALL_PROXY"] = proxy_url
        env["WS_PROXY"] = proxy_url
        env["WSS_PROXY"] = proxy_url
        env["http_proxy"] = proxy_url
        env["https_proxy"] = proxy_url
        env["all_proxy"] = proxy_url
        env["ws_proxy"] = proxy_url
        env["wss_proxy"] = proxy_url

    env["NO_PROXY"] = _LOOPBACK_NO_PROXY
    env["no_proxy"] = _LOOPBACK_NO_PROXY

    if codex_ca_certificate is not None:
        env["CODEX_CA_CERTIFICATE"] = codex_ca_certificate
    if home_dir is not None:
        if client_name is None:
            raise ValueError(f"unmapped managed client home dir: {client_name!r}")
        try:
            env_key = _HOME_DIR_ENV_BY_CLIENT[client_name]
        except KeyError as exc:
            raise ValueError(f"unmapped managed client home dir: {client_name!r}") from exc
        env[env_key] = str(home_dir)
    if extra_env is not None:
        env.update(extra_env)
    return env


def run_with_workspace_manifest(
    *,
    working_dir: Path,
    storage_dir: Path,
    run_id: str,
    home_dir: Path | None = None,
    run_launch: Callable[[Callable[[int, int], None]], None],
) -> None:
    """Acquire the per-run lock, manage the manifest, and run the launch.

    The lock lives under the run directory ``{slug}/{hash}/{run_id}/``,
    not the shared workspace container. Each launch has a fresh ``run_id``,
    so the lock never contends: it is a per-run liveness beacon that
    ``instances`` / ``paths`` probe to tell a live run from a stale
    manifest, not a gate against a second instance in the same CWD.
    """
    wid = workspace_id(working_dir)
    run_dir = run_root(working_dir, run_id)
    with WorkspaceLock(run_dir) as wslock:

        def write_manifest_for(proxy_port: int, web_port: int) -> None:
            manifest_write(
                wslock.manifest_path,
                Manifest(
                    cwd=str(working_dir),
                    pid=os.getpid(),
                    proxy_port=proxy_port,
                    web_port=web_port,
                    storage_dir=str(storage_dir),
                    run_id=run_id,
                    started_at=datetime.now(UTC).isoformat(),
                    transport_matters_version=__version__,
                    slug=wid.slug,
                    hash=wid.hash,
                    home_dir=str(home_dir) if home_dir is not None else None,
                ),
            )

        try:
            run_launch(write_manifest_for)
        finally:
            with contextlib.suppress(FileNotFoundError):
                wslock.manifest_path.unlink()
