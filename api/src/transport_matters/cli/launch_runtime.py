"""CLI launch preparation and user-facing launch errors."""

import shutil
import sysconfig
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from transport_matters.capabilities import (
    WhichFunction,
    resolve_harness_binary,
    resolve_runnable_binary,
)
from transport_matters.channel import resolve_channel_spec
from transport_matters.config import ensure_settings_scaffold, get_settings
from transport_matters.session_store_preflight import check_session_store, session_store_setup_help
from transport_matters.workspace import run_root

from .identity import CLI_COMMAND, PRODUCT_LABEL
from .ports import PortAllocationError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from importlib.resources.abc import Traversable

    from .runner import ManagedClient


@dataclass(frozen=True)
class LaunchPreparation:
    addon_traversable: Traversable
    mitmdump: str
    client_path: str | None
    working_dir: Path
    proxy_port: int
    web_port: int | None
    proxy_user_supplied: bool
    web_user_supplied: bool
    run_id: str
    resolved_storage: Path
    passthrough_user: tuple[str, ...]


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

    client_path = resolve_harness_binary(
        name=name,
        bin_override=bin_override,
        which=which,
    )
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
        resolved = resolve_runnable_binary("mitmdump", which=which, path=scripts_dir)
        if resolved is not None:
            return resolved
    return resolve_runnable_binary("mitmdump", which=which)


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


def _raise_port_in_use(label: str, flag: str, port: int) -> None:
    typer.secho(
        f"error: {label} port {port} is already in use.",
        fg=typer.colors.RED,
        err=True,
    )
    typer.echo(
        f"Another process is already bound to this port. Free it, or pick a different port with {flag}.",
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
    web_required: bool = True,
    use_channel_defaults: bool = True,
) -> tuple[int, int | None, bool, bool]:
    """Resolve the proxy and web ports, preserving which ones were pinned."""
    proxy_user_supplied = proxy_port is not None
    web_user_supplied = web_port is not None
    channel_spec = resolve_channel_spec() if use_channel_defaults else None

    if not web_required:
        if web_port is not None:
            raise ValueError("capture-only launches must not include a web port")
        if proxy_port is None:
            if channel_spec is None:
                try:
                    proxy_port, _unused_web = allocate_port_pair()
                except PortAllocationError as exc:
                    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
                    raise typer.Exit(2) from exc
            else:
                proxy_port = channel_spec.proxy_port
        assert proxy_port is not None
        proxy_pinned = proxy_user_supplied or channel_spec is not None
        if proxy_pinned and port_in_use(proxy_port):
            _raise_port_in_use("proxy", "--proxy-port", proxy_port)
        return proxy_port, None, proxy_pinned, False

    if proxy_port is None or web_port is None:
        if channel_spec is None:
            try:
                allocated_proxy, allocated_web = allocate_port_pair()
            except PortAllocationError as exc:
                typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(2) from exc
        else:
            allocated_proxy = channel_spec.proxy_port
            allocated_web = channel_spec.web_port
        if proxy_port is None:
            proxy_port = allocated_proxy
        if web_port is None:
            web_port = allocated_web
    assert proxy_port is not None
    assert web_port is not None
    proxy_pinned = proxy_user_supplied or channel_spec is not None
    web_pinned = web_user_supplied or channel_spec is not None

    for label, flag, port, pinned in (
        ("proxy", "--proxy-port", proxy_port, proxy_pinned),
        ("web UI", "--web-port", web_port, web_pinned),
    ):
        if pinned and port_in_use(port):
            _raise_port_in_use(label, flag, port)

    return proxy_port, web_port, proxy_pinned, web_pinned


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


def preflight_session_store_or_exit() -> None:
    """Scaffold settings.toml and hard-block the launch if the session store is unusable.

    Runs in the shared launch path before the proxy, agent, or Electron viewer spawn:
    creates the starter ``settings.toml`` from the packaged example if absent, then
    resolves and connects to the database. On failure it prints actionable setup
    instructions and exits non-zero, so no launch proceeds against a dead store (the
    canvas would otherwise surface a bare 503).
    """
    ensure_settings_scaffold()
    # The scaffold may have just written settings.toml; drop any settings cached before it.
    get_settings.cache_clear()
    error = check_session_store()
    if error is None:
        return
    typer.secho(f"error: {error}", fg=typer.colors.RED, err=True)
    typer.echo(session_store_setup_help(), err=True)
    raise typer.Exit(2)


def prepare_launch(
    *,
    passthrough: list[str],
    directory: Path | None,
    proxy_port: int | None,
    web_port: int | None,
    storage_dir: Path | None,
    harness: str,
    bin_override: Path | None,
    client_disabled: bool,
    not_found_hint: str,
    require_addon: Callable[[], Traversable],
    resolve_mitmdump: Callable[[], str | None],
    which: Callable[[str], str | None],
    port_in_use: Callable[[int], bool],
    allocate_port_pair: Callable[[], tuple[int, int]],
    validate_after_client_resolution: Callable[[], None] | None = None,
    web_required: bool = True,
    use_channel_defaults: bool = True,
) -> LaunchPreparation:
    """Resolve the shared launch state in the legacy command order."""
    addon_traversable = require_addon()
    mitmdump = resolve_mitmdump_or_exit(resolve_mitmdump=resolve_mitmdump)
    client_path = resolve_client_binary(
        name=harness,
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
        web_required=web_required,
        use_channel_defaults=use_channel_defaults,
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
