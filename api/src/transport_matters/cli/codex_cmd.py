"""Implementation of the `transport-matters codex` command."""

import contextlib
import os
import shutil
import tempfile
from datetime import datetime
from importlib.resources import as_file
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from .home_seed import seed_home_dir
from .identity import CLI_COMMAND, PRODUCT_LABEL
from .launch_profile import (
    CodexLaunchProfile,
    persist_owned_session_facts,
    prepare_managed_session,
)
from .launch_runtime import (
    CLIENT_NAME_CODEX,
    build_launch_env,
    build_managed_child_env,
    build_mitmdump_argv,
    preflight_session_store_or_exit,
    prepare_launch,
    print_invocation,
    reject_passthrough_without_client,
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
    from importlib.resources.abc import Traversable

    from .launch_profile import LaunchProfile, ManagedSession


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
            stack.enter_context(tempfile.TemporaryDirectory(prefix="transport-matters-codex-ca-"))
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
        f"HTTP_PROXY={loopback_http_url(proxy_port)} HTTPS_PROXY={loopback_http_url(proxy_port)}"
    )
    if codex_ca_certificate is not None:
        return (f"{proxy_env} CODEX_CA_CERTIFICATE={codex_ca_certificate} codex",)
    return (
        f"{proxy_env} codex",
        "Set CODEX_CA_CERTIFICATE to a PEM bundle that includes the active "
        "system roots and ~/.mitmproxy/mitmproxy-ca-cert.pem.",
    )


def _build_codex_invocation(
    *,
    addon_path: Path,
    force_http_fallback_addon_path: Path | None,
    mitmdump: str,
    working_dir: Path,
    resolved_storage: Path,
    run_id: str,
    home_dir: Path | None,
    codex_path: str | None,
    codex_passthrough_user: Sequence[str],
    codex_ca_certificate: str | None,
    profile: LaunchProfile,
    managed_session: ManagedSession | None,
    debug: bool,
) -> Callable[[int, int], tuple[list[str], dict[str, str], ManagedClient | None]]:
    """Build the retry-safe invocation factory for `transport-matters codex`.

    ``managed_session`` is the §5.2b/§5.2c owned session (minted once, before the retry loop, so every
    attempt resumes the SAME owned rollout): its native id + descriptor flow to the addon via the
    launch env, and ``profile.client_argv`` injects ``codex resume <native>`` to continue the
    pre-seeded rollout TM owns. ``None`` for an un-owned launch (proxy-only or a user-pinned resume)."""

    def build_invocation(
        proxy_port: int,
        web_port: int,
    ) -> tuple[list[str], dict[str, str], ManagedClient | None]:
        native_session_id = (
            managed_session.native_session_id if managed_session is not None else None
        )
        env = build_launch_env(
            working_dir=working_dir,
            storage_dir=resolved_storage,
            proxy_port=proxy_port,
            web_port=web_port,
            run_id=run_id,
            cli=CLIENT_NAME_CODEX,
            home_dir=home_dir,
            owned_native_session_id=native_session_id,
            owned_source_descriptor=(
                managed_session.source_descriptor if managed_session is not None else None
            ),
        )

        proxy_url = loopback_http_url(proxy_port)

        extra_addons: tuple[Path, ...] = ()
        if force_http_fallback_addon_path is not None:
            extra_addons = (force_http_fallback_addon_path,)
        argv = build_mitmdump_argv(
            mitmdump=mitmdump,
            mode="regular",
            proxy_port=proxy_port,
            addon_path=addon_path,
            debug=debug,
            extra_addons=extra_addons,
        )

        client = None
        if codex_path is not None:
            client_env = build_managed_child_env(
                env,
                client_name=CLIENT_NAME_CODEX,
                home_dir=home_dir,
                proxy_url=proxy_url,
                codex_ca_certificate=codex_ca_certificate,
            )
            # The codex profile owns the argv shape (§5.2c): the top-level `-c` policy, then
            # ``resume <native>`` to continue the owned rollout, then user passthrough.
            client = ManagedClient(
                name=CLIENT_NAME_CODEX,
                display_name="Codex",
                argv=profile.client_argv(
                    client_path=codex_path,
                    passthrough=codex_passthrough_user,
                    native_session_id=native_session_id,
                ),
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
    build_invocation: Callable[[int, int], tuple[list[str], dict[str, str], ManagedClient | None]],
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
    home_dir: Path | None,
    codex_bin: Path | None,
    no_codex: bool,
    debug: bool,
    force_http_fallback: bool,
    print_command: bool,
    require_addon: Callable[[], Traversable],
    require_force_http_fallback_addon: Callable[[], Traversable],
    resolve_mitmdump: Callable[[], str | None],
    which: Callable[[str], str | None] = shutil.which,
    port_in_use: Callable[[int], bool],
    allocate_port_pair: Callable[[], tuple[int, int]],
    resolve_codex_ca_certificate: Callable[..., Path],
    print_client_banner: Callable[..., None],
    run_client_with_retry: Callable[..., None],
) -> None:
    """Execute the `codex` launch lifecycle."""
    reject_passthrough_without_client(
        disabled=no_codex,
        passthrough=codex_passthrough,
        flag="--no-codex",
    )

    # Hard-block the launch if the session store is unconfigured/unreachable, so the
    # canvas never opens against a dead store (a dry --print-command run is exempt).
    if not print_command:
        preflight_session_store_or_exit()

    prepared = prepare_launch(
        passthrough=codex_passthrough,
        directory=directory,
        proxy_port=proxy_port,
        web_port=web_port,
        storage_dir=storage_dir,
        client_name=CLIENT_NAME_CODEX,
        bin_override=codex_bin,
        client_disabled=no_codex,
        not_found_hint=(
            "Install Codex, or point at an existing binary:\n"
            f"  {CLI_COMMAND} codex --codex-bin /path/to/codex\n"
            "  # or run proxy-only:\n"
            f"  {CLI_COMMAND} codex --no-codex"
        ),
        require_addon=require_addon,
        resolve_mitmdump=resolve_mitmdump,
        which=which,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
    )

    with (
        as_file(prepared.addon_traversable) as addon_path,
        contextlib.ExitStack() as stack,
    ):
        force_http_fallback_addon_path: Path | None = None
        if force_http_fallback:
            force_http_fallback_traversable = require_force_http_fallback_addon()
            force_http_fallback_addon_path = Path(
                stack.enter_context(as_file(force_http_fallback_traversable))
            )
        codex_ca_certificate = None
        if prepared.client_path is not None:
            codex_ca_certificate = _resolve_codex_ca_certificate_or_exit(
                stack=stack,
                print_command=print_command,
                resolve_codex_ca_certificate=resolve_codex_ca_certificate,
            )
        elif not print_command:
            codex_ca_certificate = _resolve_proxy_only_codex_ca_hint(env=os.environ)
        # Managed-mint (§5.2b/§5.2c): mint the native uuid + pre-seed the rollout ONCE, before the
        # retry loop, so every attempt resumes the same owned session. Codex flows through the SAME
        # shared launch path claude uses (the codex profile owns the seed + argv shape); ``write`` is
        # gated on print-command (dry run touches no disk). ``None`` when proxy-only or the user passed
        # their own `resume` (honor passthrough).
        profile = CodexLaunchProfile()
        managed_session = prepare_managed_session(
            profile,
            client_path=prepared.client_path,
            passthrough=prepared.passthrough_user,
            working_dir=prepared.working_dir,
            home_dir=home_dir,
            env=os.environ,
            now=datetime.now().astimezone(),
            write=not print_command,
        )
        build_invocation = _build_codex_invocation(
            addon_path=addon_path,
            force_http_fallback_addon_path=force_http_fallback_addon_path,
            mitmdump=prepared.mitmdump,
            working_dir=prepared.working_dir,
            resolved_storage=prepared.resolved_storage,
            run_id=prepared.run_id,
            home_dir=home_dir,
            codex_path=prepared.client_path,
            codex_passthrough_user=prepared.passthrough_user,
            codex_ca_certificate=codex_ca_certificate,
            profile=profile,
            managed_session=managed_session,
            debug=debug,
        )

        if print_command:
            print_invocation(
                build_invocation=build_invocation,
                proxy_port=prepared.proxy_port,
                web_port=prepared.web_port,
            )
        if not print_command and home_dir is not None and prepared.client_path is not None:
            seed_home_dir(
                CLIENT_NAME_CODEX,
                home_dir=home_dir,
                working_dir=prepared.working_dir,
            )

        def run_launch(write_manifest_for: Callable[[int, int], None]) -> None:
            # Durable owned-launch facts (§11.1): written once here, inside the per-run lock (the run
            # dir exists) and before the retry loop, so a §10.5 rebuild reads the owned state without
            # the live env. ``None`` for proxy-only / user-pinned resume (nothing owned to persist).
            if managed_session is not None:
                persist_owned_session_facts(
                    profile,
                    managed_session,
                    run_id=prepared.run_id,
                    storage_root=prepared.resolved_storage,
                    home_dir=home_dir,
                )
            _run_codex_launch(
                proxy_port=prepared.proxy_port,
                web_port=prepared.web_port,
                proxy_user_supplied=prepared.proxy_user_supplied,
                web_user_supplied=prepared.web_user_supplied,
                no_codex=no_codex,
                codex_ca_certificate=codex_ca_certificate,
                working_dir=prepared.working_dir,
                resolved_storage=prepared.resolved_storage,
                build_invocation=build_invocation,
                print_client_banner=print_client_banner,
                run_client_with_retry=run_client_with_retry,
                write_manifest_for=write_manifest_for,
            )

        run_with_workspace_manifest(
            working_dir=prepared.working_dir,
            storage_dir=prepared.resolved_storage,
            run_id=prepared.run_id,
            home_dir=home_dir,
            run_launch=run_launch,
        )
