"""Implementation of the `transport-matters codex` command."""

import atexit
import contextlib
import hashlib
import os
import shutil
import ssl
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import as_file
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from transport_matters.captured_run import require_web_port
from transport_matters.launch_environment import (
    CLIENT_NAME_CODEX,
    build_launch_env,
    build_managed_child_env,
)
from transport_matters.launch_manifest import run_with_workspace_manifest

from .identity import CLI_COMMAND, PRODUCT_LABEL
from .launch_profile import (
    CodexLaunchProfile,
    persist_owned_session_facts,
    prepare_managed_session,
)
from .launch_runtime import (
    build_mitmdump_argv,
    preflight_session_store_or_exit,
    prepare_launch,
    print_invocation,
    reject_passthrough_without_client,
)
from .net import loopback_http_url
from .runner import ManagedClient
from .runtime_home import (
    RuntimeHomePlan,
    plan_runtime_home,
    prepare_runtime_home,
    seed_direct_home_if_needed,
)
from .trust import (
    ConfiguredCACertificateMissingError,
    MitmproxyCAMissingError,
    SystemTrustSnapshotError,
    TrustBundleWriteError,
    mitmproxy_ca_cert_path,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from importlib.resources.abc import Traversable

    from .launch_profile import LaunchProfile, ManagedSession
    from .launch_runtime import LaunchPreparation


@dataclass(frozen=True)
class _CodexLaunchParts:
    runtime_home_plan: RuntimeHomePlan
    profile: LaunchProfile
    managed_session: ManagedSession | None
    build_invocation: Callable[
        [int, int | None],
        tuple[list[str], dict[str, str], ManagedClient | None],
    ]


@dataclass(frozen=True, slots=True)
class _PathFingerprint:
    path: str
    mtime_ns: int | None
    size: int | None
    inode: int | None


@dataclass(frozen=True, slots=True)
class _CodexCACacheKey:
    resolver_id: int
    env_digest: str
    mitmproxy_ca: _PathFingerprint
    trust_paths: tuple[_PathFingerprint, ...]


_CODEX_CA_CACHE_LOCK = threading.Lock()
_CODEX_CA_CACHE: dict[_CodexCACacheKey, str] = {}
_CODEX_CA_CACHE_BUNDLE_DIRS: set[Path] = set()
_CODEX_CA_CLEANUP_REGISTERED = False


def _resolve_codex_ca_certificate_or_exit(
    *,
    stack: contextlib.ExitStack,
    print_command: bool,
    resolve_codex_ca_certificate: Callable[..., Path],
    env: Mapping[str, str] = os.environ,
) -> str | None:
    """Resolve the Codex trust bundle or surface a user-facing error."""
    if print_command:
        return None
    _ = stack

    try:
        if env.get("CODEX_CA_CERTIFICATE"):
            return str(
                resolve_codex_ca_certificate(
                    env=env,
                    bundle_dir=None,
                )
            )
        return _resolve_generated_codex_ca_certificate(
            resolve_codex_ca_certificate=resolve_codex_ca_certificate,
            env=env,
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


def _resolve_generated_codex_ca_certificate(
    *,
    resolve_codex_ca_certificate: Callable[..., Path],
    env: Mapping[str, str],
) -> str:
    cache_key = _codex_ca_cache_key(
        resolve_codex_ca_certificate=resolve_codex_ca_certificate, env=env
    )
    with _CODEX_CA_CACHE_LOCK:
        cached = _CODEX_CA_CACHE.get(cache_key)
        if cached is not None and Path(cached).is_file():
            return cached
        bundle_dir = Path(tempfile.mkdtemp(prefix="transport-matters-codex-ca-"))
        try:
            resolved = str(
                resolve_codex_ca_certificate(
                    env=env,
                    bundle_dir=bundle_dir,
                )
            )
        except Exception:
            shutil.rmtree(bundle_dir, ignore_errors=True)
            raise
        _CODEX_CA_CACHE[cache_key] = resolved
        _register_codex_ca_bundle_dir_for_exit_cleanup(bundle_dir)
        return resolved


def _codex_ca_cache_key(
    *, resolve_codex_ca_certificate: Callable[..., Path], env: Mapping[str, str]
) -> _CodexCACacheKey:
    verify_paths = ssl.get_default_verify_paths()
    trust_path_values = (
        verify_paths.cafile,
        verify_paths.capath,
        verify_paths.openssl_cafile,
        verify_paths.openssl_capath,
    )
    return _CodexCACacheKey(
        resolver_id=id(resolve_codex_ca_certificate),
        env_digest=_env_digest(env),
        mitmproxy_ca=_path_fingerprint(mitmproxy_ca_cert_path()),
        trust_paths=tuple(
            _path_fingerprint(Path(path))
            for path in dict.fromkeys(path for path in trust_path_values if path)
        ),
    )


def _env_digest(env: Mapping[str, str]) -> str:
    digest = hashlib.blake2b(digest_size=16)
    for key, value in sorted(env.items()):
        digest.update(str(key).encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(value).encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
    return digest.hexdigest()


def _path_fingerprint(path: Path) -> _PathFingerprint:
    candidate = path.expanduser()
    try:
        stat = candidate.stat()
    except OSError:
        return _PathFingerprint(str(candidate), None, None, None)
    try:
        display_path = str(candidate.resolve())
    except OSError:
        display_path = str(candidate)
    return _PathFingerprint(
        display_path,
        stat.st_mtime_ns,
        stat.st_size,
        getattr(stat, "st_ino", None),
    )


def _reset_codex_ca_certificate_cache_for_tests() -> None:
    global _CODEX_CA_CLEANUP_REGISTERED
    _cleanup_codex_ca_cache_for_process_exit()
    _CODEX_CA_CLEANUP_REGISTERED = False


def _register_codex_ca_bundle_dir_for_exit_cleanup(bundle_dir: Path) -> None:
    global _CODEX_CA_CLEANUP_REGISTERED
    _CODEX_CA_CACHE_BUNDLE_DIRS.add(bundle_dir)
    if not _CODEX_CA_CLEANUP_REGISTERED:
        atexit.register(_cleanup_codex_ca_cache_for_process_exit)
        _CODEX_CA_CLEANUP_REGISTERED = True


def _cleanup_codex_ca_cache_for_process_exit() -> None:
    with _CODEX_CA_CACHE_LOCK:
        bundle_dirs = tuple(_CODEX_CA_CACHE_BUNDLE_DIRS)
        _CODEX_CA_CACHE_BUNDLE_DIRS.clear()
        _CODEX_CA_CACHE.clear()
    for bundle_dir in bundle_dirs:
        shutil.rmtree(bundle_dir, ignore_errors=True)


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


def build_codex_invocation(
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
    web_runtime: str = "embedded",
    default_client_passthrough: Sequence[str] = (),
    runtime_home_dir: Path | None = None,
    launch_fields: Mapping[str, object] | None = None,
) -> Callable[[int, int | None], tuple[list[str], dict[str, str], ManagedClient | None]]:
    """Build the retry-safe invocation factory for `transport-matters codex`.

    ``managed_session`` is the §5.2b/§5.2c owned session (minted once, before the retry loop, so every
    attempt resumes the SAME owned rollout): its native id + descriptor flow to the addon via the
    launch env, and ``profile.client_argv`` injects ``codex resume <native>`` to continue the
    pre-seeded rollout TM owns. ``None`` for an un-owned launch (proxy-only or a user-pinned resume)."""

    def build_invocation(
        proxy_port: int,
        web_port: int | None,
    ) -> tuple[list[str], dict[str, str], ManagedClient | None]:
        if web_runtime == "embedded":
            web_port = require_web_port(web_port)
        native_session_id = (
            managed_session.native_session_id if managed_session is not None else None
        )
        env = build_launch_env(
            working_dir=working_dir,
            storage_dir=resolved_storage,
            proxy_port=proxy_port,
            web_port=web_port,
            run_id=run_id,
            web_runtime=web_runtime,
            cli=CLIENT_NAME_CODEX,
            home_dir=home_dir,
            owned_native_session_id=native_session_id,
            owned_source_descriptor=(
                managed_session.source_descriptor if managed_session is not None else None
            ),
            launch_fields=launch_fields,
            default_client_passthrough=default_client_passthrough,
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
                home_dir=runtime_home_dir or home_dir,
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


def resolve_codex_addons_and_ca(
    *,
    stack: contextlib.ExitStack,
    force_http_fallback: bool,
    require_force_http_fallback_addon: Callable[[], Traversable],
    client_path: str | None,
    print_command: bool,
    resolve_codex_ca_certificate: Callable[..., Path],
    env: Mapping[str, str] = os.environ,
) -> tuple[Path | None, str | None]:
    """Resolve the optional force-HTTP-fallback addon path and the Codex CA bundle."""
    force_http_fallback_addon_path: Path | None = None
    if force_http_fallback:
        force_http_fallback_addon_path = Path(
            stack.enter_context(as_file(require_force_http_fallback_addon()))
        )
    codex_ca_certificate: str | None = None
    if client_path is not None:
        codex_ca_certificate = _resolve_codex_ca_certificate_or_exit(
            stack=stack,
            print_command=print_command,
            resolve_codex_ca_certificate=resolve_codex_ca_certificate,
            env=env,
        )
    elif not print_command:
        codex_ca_certificate = _resolve_proxy_only_codex_ca_hint(env=env)
    return force_http_fallback_addon_path, codex_ca_certificate


def _prepare_codex_launch_parts(
    *,
    stack: contextlib.ExitStack,
    addon_path: Path,
    force_http_fallback_addon_path: Path | None,
    codex_ca_certificate: str | None,
    prepared: LaunchPreparation,
    home_dir: Path | None,
    print_command: bool,
    debug: bool,
    default_client_passthrough: Sequence[str],
    env: Mapping[str, str] = os.environ,
) -> _CodexLaunchParts:
    runtime_home_root = prepared.resolved_storage / "runtime-home"
    runtime_home_plan = plan_runtime_home(
        CLIENT_NAME_CODEX,
        home_dir=home_dir,
        runtime_template=None,
        runtime_home_root=runtime_home_root,
        client_path=prepared.client_path,
        env=env,
        use_runtime_overlay=False,
    )
    runtime_home_dir = None
    if not print_command and prepare_runtime_home(
        runtime_home_plan,
        working_dir=prepared.working_dir,
        env=env,
    ):
        runtime_home_dir = runtime_home_plan.runtime_home_dir
        stack.callback(shutil.rmtree, runtime_home_root, ignore_errors=True)

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
        home_dir=runtime_home_plan.descriptor_home,
        env=env,
        now=datetime.now().astimezone(),
        write=not print_command,
    )
    build_invocation = build_codex_invocation(
        addon_path=addon_path,
        force_http_fallback_addon_path=force_http_fallback_addon_path,
        mitmdump=prepared.mitmdump,
        working_dir=prepared.working_dir,
        resolved_storage=prepared.resolved_storage,
        run_id=prepared.run_id,
        home_dir=runtime_home_plan.descriptor_home,
        runtime_home_dir=runtime_home_dir,
        codex_path=prepared.client_path,
        codex_passthrough_user=prepared.passthrough_user,
        codex_ca_certificate=codex_ca_certificate,
        profile=profile,
        managed_session=managed_session,
        debug=debug,
        default_client_passthrough=default_client_passthrough,
        launch_fields=runtime_home_plan.launch_fields,
    )
    return _CodexLaunchParts(
        runtime_home_plan=runtime_home_plan,
        profile=profile,
        managed_session=managed_session,
        build_invocation=build_invocation,
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
    default_client_passthrough: tuple[str, ...] = (),
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
        force_http_fallback_addon_path, codex_ca_certificate = resolve_codex_addons_and_ca(
            stack=stack,
            force_http_fallback=force_http_fallback,
            require_force_http_fallback_addon=require_force_http_fallback_addon,
            client_path=prepared.client_path,
            print_command=print_command,
            resolve_codex_ca_certificate=resolve_codex_ca_certificate,
        )
        launch_parts = _prepare_codex_launch_parts(
            stack=stack,
            addon_path=addon_path,
            force_http_fallback_addon_path=force_http_fallback_addon_path,
            codex_ca_certificate=codex_ca_certificate,
            prepared=prepared,
            home_dir=home_dir,
            debug=debug,
            print_command=print_command,
            default_client_passthrough=default_client_passthrough,
        )
        prepared_web_port = require_web_port(prepared.web_port)

        if print_command:
            print_invocation(
                build_invocation=launch_parts.build_invocation,
                proxy_port=prepared.proxy_port,
                web_port=prepared_web_port,
            )
        if not print_command:
            seed_direct_home_if_needed(
                launch_parts.runtime_home_plan,
                working_dir=prepared.working_dir,
                env=os.environ,
            )

        def run_launch(write_manifest_for: Callable[[int, int], None]) -> None:
            # Durable owned-launch facts (§11.1): written once here, inside the per-run lock (the run
            # dir exists) and before the retry loop, so a §10.5 rebuild reads the owned state without
            # the live env. ``None`` for proxy-only / user-pinned resume (nothing owned to persist).
            if launch_parts.managed_session is not None:
                persist_owned_session_facts(
                    launch_parts.profile,
                    launch_parts.managed_session,
                    run_id=prepared.run_id,
                    storage_root=prepared.resolved_storage,
                    home_dir=launch_parts.runtime_home_plan.descriptor_home,
                    template_provenance=launch_parts.runtime_home_plan.template_provenance_field,
                )
            _run_codex_launch(
                proxy_port=prepared.proxy_port,
                web_port=prepared_web_port,
                proxy_user_supplied=prepared.proxy_user_supplied,
                web_user_supplied=prepared.web_user_supplied,
                no_codex=no_codex,
                codex_ca_certificate=codex_ca_certificate,
                working_dir=prepared.working_dir,
                resolved_storage=prepared.resolved_storage,
                build_invocation=launch_parts.build_invocation,
                print_client_banner=print_client_banner,
                run_client_with_retry=run_client_with_retry,
                write_manifest_for=write_manifest_for,
            )

        run_with_workspace_manifest(
            working_dir=prepared.working_dir,
            storage_dir=prepared.resolved_storage,
            run_id=prepared.run_id,
            home_dir=launch_parts.runtime_home_plan.descriptor_home,
            run_launch=run_launch,
        )
