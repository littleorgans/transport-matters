"""Supervisor-driven lifecycle for Transport Matters launch commands.

Owns both child processes end to end: spawn mitmdump, wait for readiness,
spawn the managed client, then translate whichever child exits first into a
sensible top-level exit code. See the `run_client_children_until_outcome`
docstring for the full decision matrix.

The startup window also detects ``EADDRINUSE``-shaped failures and
surfaces them as :class:`BindFailure` rather than ``typer.Exit(1)`` —
the caller catches that to drive the spec's bounded
allocate-→-spawn retry loop. The bind-failure detection and retry
policy live in :mod:`bind_failure`; the shared outcome types live in
:mod:`launch_outcomes`. Both are re-exported here so the historical
``from .runner import …`` surface stays intact.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer

from transport_matters.supervisor import SIGNAL_EXIT, ProcessSupervisor

from .bind_failure import (
    BIND_RETRY_ATTEMPTS,
    failing_ports_from_log,
    format_retry_exhaustion,
    handle_bind_failure,
)
from .launch_outcomes import (
    PROXY_START_TIMEOUT_MESSAGE,
    BindFailure,
    LaunchBindFailureOutcome,
    LaunchExitOutcome,
    LaunchOutcome,
    LaunchRetryExhaustedOutcome,
)
from .net import loopback_http_url, wait_for_port_ready

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "PROXY_START_TIMEOUT_MESSAGE",
    "BindFailure",
    "LaunchBindFailureOutcome",
    "LaunchExitOutcome",
    "LaunchRetryExhaustedOutcome",
    "ManagedClient",
    "_run_client_children",
    "failing_ports_from_log",
    "format_retry_exhaustion",
    "handle_bind_failure",
    "mitmdump_log_path",
    "run_children",
    "run_client_children_until_outcome",
    "run_client_with_retry",
    "run_prepared_client_on_local_tty",
    "start_prepared_proxy",
]


@dataclass(frozen=True)
class ManagedClient:
    """Descriptor for the foreground interactive child process."""

    name: str
    display_name: str
    argv: list[str]
    env: dict[str, str]
    cwd: Path


def _bind_backend_ready_hook(
    hook: Callable[[dict[str, str], Path, ManagedClient | None, int, int], None],
    *,
    launch_env: dict[str, str],
    resolved_storage: Path,
    client: ManagedClient | None,
    proxy_port: int,
    web_port: int,
) -> Callable[[], None]:
    def notify_backend_ready() -> None:
        hook(launch_env, resolved_storage, client, proxy_port, web_port)

    return notify_backend_ready


def _notify_backend_ready(
    sup: ProcessSupervisor,
    on_backend_ready: Callable[[], None],
) -> None:
    try:
        on_backend_ready()
    except Exception:
        sup.terminate_all()
        raise


def _wait_web_ui_ready_for_hook(
    *,
    sup: ProcessSupervisor,
    proxy_port: int,
    web_port: int,
    log_path: Path | None,
) -> LaunchOutcome | None:
    if wait_for_port_ready("127.0.0.1", web_port):
        return None
    sup.terminate_all()
    if log_path is not None:
        failing = failing_ports_from_log(log_path, (proxy_port, web_port))
        if failing is not None:
            return LaunchBindFailureOutcome(
                BindFailure(
                    proxy_port=proxy_port,
                    web_port=web_port,
                    failing_ports=failing,
                    log_path=log_path,
                )
            )
    return LaunchExitOutcome(
        exit_code=1,
        error="web UI did not come up within 5s.",
        log_path=log_path,
    )


def _proxy_not_ready_outcome(
    *,
    sup: ProcessSupervisor,
    proxy_port: int,
    web_port: int | None,
    log_path: Path,
) -> LaunchOutcome:
    attempted_ports = (proxy_port,) if web_port is None else (proxy_port, web_port)
    failing = failing_ports_from_log(log_path, attempted_ports)
    if failing is not None:
        sup.terminate_all()
        return LaunchBindFailureOutcome(
            BindFailure(
                proxy_port=proxy_port,
                web_port=web_port,
                failing_ports=failing,
                log_path=log_path,
            )
        )
    sup.terminate_all()
    return LaunchExitOutcome(
        exit_code=1,
        error=PROXY_START_TIMEOUT_MESSAGE,
        log_path=log_path,
    )


def _raise_retry_exhausted(outcome: LaunchRetryExhaustedOutcome) -> None:
    lines = format_retry_exhaustion(outcome)
    typer.secho(lines[0], fg=typer.colors.RED, err=True)
    for line in lines[1:]:
        typer.echo(line, err=True)
    raise typer.Exit(1)


def run_client_with_retry(
    *,
    proxy_port: int,
    web_port: int,
    proxy_user_supplied: bool,
    web_user_supplied: bool,
    build_invocation: Callable[[int, int], tuple[list[str], dict[str, str], ManagedClient | None]],
    print_banner_for: Callable[[int, int], None],
    write_manifest_for: Callable[[int, int], None],
    resolved_storage: Path,
    on_backend_ready: Callable[[dict[str, str], Path, ManagedClient | None, int, int], None]
    | None = None,
) -> None:
    """Run the spawn lifecycle with bounded allocate-→-spawn retry.

    Loops up to :data:`BIND_RETRY_ATTEMPTS` attempts. Each attempt
    refreshes the manifest with the current ports, re-prints the banner
    (with a "retrying" preamble after the first), rebuilds the child
    invocations via ``build_invocation``, and calls
    :func:`_run_client_children`. On :class:`BindFailure` the retry
    decision lives in :func:`handle_bind_failure`. On exhaustion we
    surface the attempted port pairs and exit non-zero with an
    actionable message.
    """
    attempted: list[tuple[int, int]] = []
    for attempt in range(BIND_RETRY_ATTEMPTS):
        attempted.append((proxy_port, web_port))
        write_manifest_for(proxy_port, web_port)
        if attempt > 0:
            typer.secho(
                f"retrying after bind conflict (attempt {attempt + 1}/{BIND_RETRY_ATTEMPTS})",
                fg=typer.colors.YELLOW,
                err=True,
            )
        print_banner_for(proxy_port, web_port)
        mitmdump_argv, child_env, client = build_invocation(proxy_port, web_port)
        notify_backend_ready = None
        if on_backend_ready is not None:
            notify_backend_ready = _bind_backend_ready_hook(
                on_backend_ready,
                launch_env=child_env,
                resolved_storage=resolved_storage,
                client=client,
                proxy_port=proxy_port,
                web_port=web_port,
            )
        try:
            _run_client_children(
                mitmdump_argv=mitmdump_argv,
                mitmdump_env=child_env,
                storage_dir=resolved_storage,
                client=client,
                proxy_port=proxy_port,
                web_port=web_port,
                on_backend_ready=notify_backend_ready,
            )
            return
        except BindFailure as exc:
            if attempt + 1 >= BIND_RETRY_ATTEMPTS:
                break
            next_proxy_port, next_web_port = handle_bind_failure(
                exc,
                proxy_port=proxy_port,
                web_port=web_port,
                proxy_user_supplied=proxy_user_supplied,
                web_user_supplied=web_user_supplied,
            )
            if next_web_port is None:
                raise RuntimeError("CLI launch retry lost web port") from exc
            proxy_port, web_port = next_proxy_port, next_web_port

    _raise_retry_exhausted(
        LaunchRetryExhaustedOutcome(
            attempted=tuple(attempted),
            proxy_port=proxy_port,
            web_port=web_port,
            proxy_user_supplied=proxy_user_supplied,
            web_user_supplied=web_user_supplied,
        )
    )


def run_children(
    *,
    mitmdump_argv: list[str],
    mitmdump_env: dict[str, str],
    storage_dir: Path,
    claude_argv: list[str] | None,
    claude_env: dict[str, str] | None,
    claude_cwd: Path,
    proxy_port: int,
    web_port: int,
) -> None:
    """Claude-specific wrapper over the generic client lifecycle."""

    client = None
    if claude_argv is not None:
        assert claude_env is not None
        client = ManagedClient(
            name="claude",
            display_name="Claude",
            argv=claude_argv,
            env=claude_env,
            cwd=claude_cwd,
        )
    _run_client_children(
        mitmdump_argv=mitmdump_argv,
        mitmdump_env=mitmdump_env,
        storage_dir=storage_dir,
        client=client,
        proxy_port=proxy_port,
        web_port=web_port,
    )


def _run_client_children(
    *,
    mitmdump_argv: list[str],
    mitmdump_env: dict[str, str],
    storage_dir: Path,
    client: ManagedClient | None,
    proxy_port: int,
    web_port: int,
    on_backend_ready: Callable[[], None] | None = None,
) -> None:
    """Run child processes and translate the structured outcome to CLI exit."""
    outcome = run_client_children_until_outcome(
        mitmdump_argv=mitmdump_argv,
        mitmdump_env=mitmdump_env,
        storage_dir=storage_dir,
        client=client,
        proxy_port=proxy_port,
        web_port=web_port,
        on_backend_ready=on_backend_ready,
    )
    _raise_launch_outcome(outcome)


def mitmdump_log_path(storage_dir: Path) -> Path:
    logs_dir = storage_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "mitmdump.log"


def start_prepared_proxy(
    *,
    sup: ProcessSupervisor,
    mitmdump_argv: list[str],
    mitmdump_env: dict[str, str],
    mitmdump_log: Path,
    proxy_port: int,
    web_port: int | None,
    on_backend_ready: Callable[[], None] | None = None,
) -> LaunchOutcome | None:
    """Start background mitmdump and wait until the captured backend is ready."""
    sup.spawn(
        "mitmdump",
        mitmdump_argv,
        env={**mitmdump_env, "PYTHONUNBUFFERED": "1"},
        log_path=mitmdump_log,
    )
    if not wait_for_port_ready("127.0.0.1", proxy_port):
        # Distinguish "port stolen between allocate and spawn" (retryable
        # upstairs) from "config is broken" (do not retry).
        return _proxy_not_ready_outcome(
            sup=sup,
            proxy_port=proxy_port,
            web_port=web_port,
            log_path=mitmdump_log,
        )

    if sup.received_signal is not None:
        sup.terminate_all()
        return LaunchExitOutcome(0)

    if on_backend_ready is not None:
        if web_port is None:
            raise ValueError("backend ready hook requires a web port")
        outcome = _wait_web_ui_ready_for_hook(
            sup=sup,
            proxy_port=proxy_port,
            web_port=web_port,
            log_path=mitmdump_log,
        )
        if outcome is not None:
            return outcome
        _notify_backend_ready(sup, on_backend_ready)
    return None


def run_prepared_client_on_local_tty(
    *,
    sup: ProcessSupervisor,
    client: ManagedClient,
    web_port: int,
    mitmdump_log: Path,
) -> LaunchOutcome:
    """Attach an already prepared managed client to the local terminal."""
    # Spawn the client attached to a real PTY; the supervisor keeps
    # non-interactive fallback and signal routing behavior unchanged.
    sup.spawn(
        client.name,
        client.argv,
        env=client.env,
        cwd=client.cwd,
        foreground=True,
        pty=True,
    )

    name, rc = sup.wait_any()
    if name == SIGNAL_EXIT:
        sup.terminate_all()
        return LaunchExitOutcome(0)

    if name == client.name:
        typer.secho(
            f"{client.display_name} exited; web UI still live at "
            f"{loopback_http_url(web_port)}. Ctrl+C to stop.",
            fg=typer.colors.CYAN,
        )
        # Wait on the proxy; Ctrl+C flips us into terminate_all.
        name, rc = sup.wait_one("mitmdump")
        if name == SIGNAL_EXIT:
            sup.terminate_all()
            return LaunchExitOutcome(0)
        if rc != 0:
            sup.terminate_all()
            return LaunchExitOutcome(
                exit_code=1,
                error=f"mitmdump exited unexpectedly (rc={rc}).",
                log_path=mitmdump_log,
            )
        sup.terminate_all()
        return LaunchExitOutcome(0)

    # mitmdump died first. Surface the error and tear down the client.
    sup.terminate_all()
    return LaunchExitOutcome(
        exit_code=1,
        error=f"mitmdump exited unexpectedly (rc={rc}).",
        log_path=mitmdump_log,
    )


def _raise_launch_outcome(outcome: LaunchOutcome) -> None:
    if isinstance(outcome, LaunchBindFailureOutcome):
        raise outcome.failure
    if outcome.error is not None:
        typer.secho(f"error: {outcome.error}", fg=typer.colors.RED, err=True)
    if outcome.log_path is not None:
        typer.echo(f"  See {outcome.log_path} for details.", err=True)
    raise typer.Exit(outcome.exit_code)


def run_client_children_until_outcome(
    *,
    mitmdump_argv: list[str],
    mitmdump_env: dict[str, str],
    storage_dir: Path,
    client: ManagedClient | None,
    proxy_port: int,
    web_port: int,
    on_backend_ready: Callable[[], None] | None = None,
) -> LaunchOutcome:
    """Own both child processes end to end.

    Spawn order is fixed: mitmdump first (so the proxy port is live),
    then the interactive client (pointed at the proxy, if present). We
    then wait for whichever child exits first and return a structured
    result:

    - Ctrl+C (SIGINT): terminate both, exit 0.
    - client exits first: proxy stays up, user can review the web UI;
      Ctrl+C at that point tears down the proxy.
    - mitmdump exits first: report the log path and bring down the
      client too (it has no backend anyway), exit 1.
    - proxy-only mode: mitmdump runs in the foreground; its exit code
      is ours.
    """
    # Create logs up front so later non-proxy-only launches do not race on it.
    mitmdump_log = mitmdump_log_path(storage_dir)

    sup = ProcessSupervisor()
    sup.install_signal_handlers()
    try:
        if client is None:
            # Proxy-only. mitmdump owns the terminal so its output is live.
            sup.spawn("mitmdump", mitmdump_argv, env=mitmdump_env, foreground=True)
            if on_backend_ready is not None:
                outcome = _wait_web_ui_ready_for_hook(
                    sup=sup,
                    proxy_port=proxy_port,
                    web_port=web_port,
                    log_path=None,
                )
                if outcome is not None:
                    return outcome
                _notify_backend_ready(sup, on_backend_ready)
            name, rc = sup.wait_one("mitmdump")
            if name == SIGNAL_EXIT:
                sup.terminate_all()
                return LaunchExitOutcome(0)
            # mitmdump exited on its own — propagate its code.
            return LaunchExitOutcome(rc)

        outcome = start_prepared_proxy(
            sup=sup,
            mitmdump_argv=mitmdump_argv,
            mitmdump_env=mitmdump_env,
            mitmdump_log=mitmdump_log,
            proxy_port=proxy_port,
            web_port=web_port,
            on_backend_ready=on_backend_ready,
        )
        if outcome is not None:
            return outcome
        return run_prepared_client_on_local_tty(
            sup=sup,
            client=client,
            web_port=web_port,
            mitmdump_log=mitmdump_log,
        )
    finally:
        sup.restore_signal_handlers()
