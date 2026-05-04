"""Implementation of the `transport-matters codex` command."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from importlib.resources import as_file
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from .identity import CLI_COMMAND, PRODUCT_LABEL
from .launch_runtime import (
    build_launch_env,
    build_managed_child_env,
    managed_child_shell_env_excludes,
    new_run_id,
    reject_passthrough_without_client,
    resolve_launch_ports,
    resolve_mitmdump_or_exit,
    resolve_storage_dir,
    resolve_working_dir,
    run_with_workspace_manifest,
)
from .net import loopback_http_url
from .runner import ManagedClient
from .trust import (
    ConfiguredCACertificateMissingError,
    MitmproxyCAMissingError,
    SystemTrustSnapshotError,
    TrustBundleWriteError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from importlib.abc import Traversable


def _resolve_codex_path(
    *,
    codex_bin: Path | None,
    no_codex: bool,
    which: Callable[[str], str | None],
) -> str | None:
    """Resolve the Codex binary or exit with an actionable hint."""
    if no_codex:
        return None

    codex_path = str(codex_bin) if codex_bin is not None else which("codex")
    if codex_path is not None:
        return codex_path

    typer.secho(
        "error: `codex` was not found on PATH.",
        fg=typer.colors.RED,
        err=True,
    )
    typer.echo(
        "Install Codex, or point at an existing binary:\n"
        f"  {CLI_COMMAND} codex --codex-bin /path/to/codex\n"
        "  # or run proxy-only:\n"
        f"  {CLI_COMMAND} codex --no-codex",
        err=True,
    )
    raise typer.Exit(2)


def _resolve_codex_ca_certificate_or_exit(
    *,
    stack: contextlib.ExitStack,
    print_command: bool,
    resolve_codex_ca_certificate: Callable[..., Path],
) -> str | None:
    """Resolve the Codex trust bundle or surface a user-facing error."""
    if print_command:
        return None

    bundle_dir: Path | None = None
    if not os.environ.get("CODEX_CA_CERTIFICATE"):
        bundle_dir = Path(
            stack.enter_context(
                tempfile.TemporaryDirectory(prefix="transport-matters-codex-ca-")
            )
        )
    try:
        return str(
            resolve_codex_ca_certificate(
                env=os.environ,
                bundle_dir=bundle_dir,
            )
        )
    except ConfiguredCACertificateMissingError as exc:
        typer.secho(
            "error: CODEX_CA_CERTIFICATE points to a missing file.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(f"  Expected an existing PEM bundle at {exc.path}.", err=True)
        typer.echo(
            f"  Unset CODEX_CA_CERTIFICATE to let {PRODUCT_LABEL} generate one,\n"
            "  or point it at a readable CA bundle file.",
            err=True,
        )
        raise typer.Exit(2) from exc
    except MitmproxyCAMissingError as exc:
        typer.secho(
            "error: mitmproxy CA missing for Codex trust bootstrap.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(f"  Expected public CA at {exc.path}.", err=True)
        typer.echo(
            "  Start mitmproxy once to generate the CA material, then retry.",
            err=True,
        )
        raise typer.Exit(2) from exc
    except SystemTrustSnapshotError as exc:
        typer.secho(
            "error: could not snapshot the active system trust roots.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(f"  {exc}", err=True)
        typer.echo(
            "  Codex trust bootstrap depends on Python's ssl default trust view.",
            err=True,
        )
        raise typer.Exit(2) from exc
    except TrustBundleWriteError as exc:
        typer.secho(
            "error: could not expose CODEX_CA_CERTIFICATE for Codex.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(f"  {exc}", err=True)
        raise typer.Exit(2) from exc


def _resolve_proxy_only_codex_ca_hint(*, env: Mapping[str, str]) -> str | None:
    """Return a reusable CA bundle path for proxy-only banner hints."""
    configured = env.get("CODEX_CA_CERTIFICATE")
    if not configured:
        return None

    candidate = Path(configured).expanduser()
    if not candidate.is_file():
        return None
    return str(candidate.resolve())


def _build_proxy_only_codex_hint(
    *,
    proxy_port: int,
    codex_ca_certificate: str | None,
) -> Sequence[str]:
    """Render an accurate manual Codex launch hint for proxy-only mode."""
    proxy_env = (
        f"HTTP_PROXY={loopback_http_url(proxy_port)} "
        f"HTTPS_PROXY={loopback_http_url(proxy_port)}"
    )
    if codex_ca_certificate is not None:
        return (f"{proxy_env} CODEX_CA_CERTIFICATE={codex_ca_certificate} codex",)
    return (
        f"{proxy_env} codex",
        "Set CODEX_CA_CERTIFICATE to a PEM bundle that includes the active "
        "system roots and ~/.mitmproxy/mitmproxy-ca-cert.pem.",
    )


def _codex_shell_environment_policy_args() -> list[str]:
    excluded = ",".join(json.dumps(key) for key in managed_child_shell_env_excludes())
    return ["-c", f"shell_environment_policy.exclude=[{excluded}]"]


def _build_codex_invocation(
    *,
    addon_path: Path,
    mitmdump: str,
    working_dir: Path,
    resolved_storage: Path,
    run_id: str,
    codex_path: str | None,
    codex_passthrough_user: list[str],
    codex_ca_certificate: str | None,
    debug: bool,
) -> Callable[[int, int], tuple[list[str], dict[str, str], ManagedClient | None]]:
    """Build the retry-safe invocation factory for `transport-matters codex`."""

    def build_invocation(
        proxy_port: int,
        web_port: int,
    ) -> tuple[list[str], dict[str, str], ManagedClient | None]:
        env = build_launch_env(
            working_dir=working_dir,
            storage_dir=resolved_storage,
            proxy_port=proxy_port,
            web_port=web_port,
            run_id=run_id,
        )

        proxy_url = loopback_http_url(proxy_port)

        argv = [
            mitmdump,
            "--mode",
            "regular",
            "--listen-host",
            "127.0.0.1",
            "--listen-port",
            str(proxy_port),
            "-s",
            str(addon_path),
        ]
        if not debug:
            argv.extend(["--set", "termlog_verbosity=warn"])

        client = None
        if codex_path is not None:
            client_env = build_managed_child_env(
                env,
                proxy_url=proxy_url,
                codex_ca_certificate=codex_ca_certificate,
            )
            client = ManagedClient(
                name="codex",
                display_name="Codex",
                argv=[
                    codex_path,
                    *_codex_shell_environment_policy_args(),
                    *codex_passthrough_user,
                ],
                env=client_env,
                cwd=working_dir,
            )
        return argv, env, client

    return build_invocation


def _run_codex_launch(
    *,
    proxy_port: int,
    web_port: int,
    proxy_user_supplied: bool,
    web_user_supplied: bool,
    no_codex: bool,
    codex_ca_certificate: str | None,
    working_dir: Path,
    resolved_storage: Path,
    build_invocation: Callable[
        [int, int], tuple[list[str], dict[str, str], ManagedClient | None]
    ],
    print_client_banner: Callable[..., None],
    run_client_with_retry: Callable[..., None],
    write_manifest_for: Callable[[int, int], None],
) -> None:
    """Drive the workspace-scoped retry loop for `transport-matters codex`."""

    def print_banner_for(current_proxy_port: int, current_web_port: int) -> None:
        proxy_hint = None
        if no_codex:
            proxy_hint = _build_proxy_only_codex_hint(
                proxy_port=current_proxy_port,
                codex_ca_certificate=codex_ca_certificate,
            )
        print_client_banner(
            proxy_port=current_proxy_port,
            web_port=current_web_port,
            proxy_target="explicit HTTPS proxy",
            working_dir=working_dir,
            client_label="codex",
            proxy_hint=proxy_hint,
        )

    run_client_with_retry(
        proxy_port=proxy_port,
        web_port=web_port,
        proxy_user_supplied=proxy_user_supplied,
        web_user_supplied=web_user_supplied,
        build_invocation=build_invocation,
        print_banner_for=print_banner_for,
        write_manifest_for=write_manifest_for,
        resolved_storage=resolved_storage,
    )


def run_codex(
    *,
    directory: Path | None,
    codex_passthrough: list[str],
    proxy_port: int | None,
    web_port: int | None,
    storage_dir: Path | None,
    codex_bin: Path | None,
    no_codex: bool,
    debug: bool,
    print_command: bool,
    require_addon: Callable[[], Traversable],
    resolve_mitmdump: Callable[[], str | None],
    which: Callable[[str], str | None] = shutil.which,
    port_in_use: Callable[[int], bool],
    allocate_port_pair: Callable[[], tuple[int, int]],
    resolve_codex_ca_certificate: Callable[..., Path],
    print_client_banner: Callable[..., None],
    run_client_with_retry: Callable[..., None],
    print_contention_error: Callable[..., None],
) -> None:
    """Execute the `codex` launch lifecycle."""
    reject_passthrough_without_client(
        disabled=no_codex,
        passthrough=codex_passthrough,
        flag="--no-codex",
    )

    addon_traversable = require_addon()
    mitmdump = resolve_mitmdump_or_exit(resolve_mitmdump=resolve_mitmdump)
    codex_path = _resolve_codex_path(
        codex_bin=codex_bin,
        no_codex=no_codex,
        which=which,
    )
    working_dir = resolve_working_dir(directory)
    proxy_port, web_port, proxy_user_supplied, web_user_supplied = resolve_launch_ports(
        proxy_port=proxy_port,
        web_port=web_port,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
    )
    resolved_storage = resolve_storage_dir(
        storage_dir=storage_dir,
        working_dir=working_dir,
    )
    run_id = new_run_id()
    codex_passthrough_user = list(codex_passthrough)

    with as_file(addon_traversable) as addon_path, contextlib.ExitStack() as stack:
        codex_ca_certificate = None
        if codex_path is not None:
            codex_ca_certificate = _resolve_codex_ca_certificate_or_exit(
                stack=stack,
                print_command=print_command,
                resolve_codex_ca_certificate=resolve_codex_ca_certificate,
            )
        elif not print_command:
            codex_ca_certificate = _resolve_proxy_only_codex_ca_hint(env=os.environ)
        build_invocation = _build_codex_invocation(
            addon_path=addon_path,
            mitmdump=mitmdump,
            working_dir=working_dir,
            resolved_storage=resolved_storage,
            run_id=run_id,
            codex_path=codex_path,
            codex_passthrough_user=codex_passthrough_user,
            codex_ca_certificate=codex_ca_certificate,
            debug=debug,
        )

        if print_command:
            mitmdump_argv, _env, client = build_invocation(proxy_port, web_port)
            typer.echo(" ".join(mitmdump_argv))
            if client is not None:
                typer.echo(" ".join(client.argv))
            raise typer.Exit(0)

        def run_launch(write_manifest_for: Callable[[int, int], None]) -> None:
            _run_codex_launch(
                proxy_port=proxy_port,
                web_port=web_port,
                proxy_user_supplied=proxy_user_supplied,
                web_user_supplied=web_user_supplied,
                no_codex=no_codex,
                codex_ca_certificate=codex_ca_certificate,
                working_dir=working_dir,
                resolved_storage=resolved_storage,
                build_invocation=build_invocation,
                print_client_banner=print_client_banner,
                run_client_with_retry=run_client_with_retry,
                write_manifest_for=write_manifest_for,
            )

        run_with_workspace_manifest(
            working_dir=working_dir,
            storage_dir=resolved_storage,
            run_id=run_id,
            on_locked=print_contention_error,
            run_launch=run_launch,
        )
