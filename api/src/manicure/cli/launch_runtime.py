"""Shared launch plumbing for the CLI entrypoints."""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from manicure import __version__
from manicure.lock import WorkspaceLock, WorkspaceLocked
from manicure.manifest import Manifest
from manicure.manifest import write as manifest_write
from manicure.workspace import workspace_id, workspace_root, workspace_storage

from .ports import PortAllocationError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


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
                f"or pick a different port (omit {flag} to let manicure allocate one).",
                err=True,
            )
            raise typer.Exit(2)

    return proxy_port, web_port, proxy_user_supplied, web_user_supplied


def resolve_storage_dir(*, storage_dir: Path | None, working_dir: Path) -> Path:
    """Resolve the per-workspace storage root for the launch."""
    return storage_dir if storage_dir is not None else workspace_storage(working_dir)


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
        "mitmproxy ships as a runtime dependency of manicure, so this\n"
        "usually means the install did not link the console scripts.\n"
        "\n"
        "Try one of:\n"
        "  uv tool install --force manicure     # reinstall as a tool\n"
        "  pipx reinstall manicure              # if you used pipx\n"
        "  pip install --force-reinstall manicure",
        err=True,
    )
    raise typer.Exit(2)


def new_run_id() -> str:
    """Return a fresh run identifier for the current launch."""
    return str(uuid.uuid4())


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
    env["MANICURE_STORAGE_DIR"] = str(storage_dir)
    env["MANICURE_WEB_PORT"] = str(web_port)
    env["MANICURE_PROXY_PORT"] = str(proxy_port)
    env["MANICURE_RUN_ID"] = run_id
    env["MANICURE_CWD"] = str(working_dir)
    return env


def build_managed_child_env(
    base_env: Mapping[str, str],
    *,
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
    if extra_env is not None:
        env.update(extra_env)
    return env


def run_with_workspace_manifest(
    *,
    working_dir: Path,
    storage_dir: Path,
    run_id: str,
    on_locked: Callable[[WorkspaceLocked, Path], None],
    run_launch: Callable[[Callable[[int, int], None]], None],
) -> None:
    """Acquire the workspace lock, manage the manifest, and run the launch."""
    wid = workspace_id(working_dir)
    ws_root = workspace_root(working_dir)
    try:
        with WorkspaceLock(ws_root) as wslock:

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
                        manicure_version=__version__,
                        slug=wid.slug,
                        hash=wid.hash,
                    ),
                )

            try:
                run_launch(write_manifest_for)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    wslock.manifest_path.unlink()
    except WorkspaceLocked as exc:
        on_locked(exc, working_dir)
        raise typer.Exit(2) from exc
