"""Supervisor-driven lifecycle for Transport Matters launch commands.

Owns both child processes end to end: spawn mitmdump, wait for readiness,
spawn the managed client, then translate whichever child exits first into a
sensible top-level exit code. See the `run_client_children_until_outcome`
docstring for the full decision matrix.

The startup window also detects ``EADDRINUSE``-shaped failures and
surfaces them as :class:`BindFailure` rather than ``typer.Exit(1)`` —
the caller catches that to drive the spec's bounded
allocate-→-spawn retry loop. Other startup failures still raise
``typer.Exit(1)`` with the message printed inline, so a broken config
keeps failing fast rather than burning retry budget.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer

from transport_matters.supervisor import SIGNAL_EXIT, ProcessSupervisor

from .net import loopback_http_url, wait_for_port_ready
from .ports import PortAllocationError, allocate_port_pair

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "BindFailure",
    "LaunchBindFailureOutcome",
    "LaunchExitOutcome",
    "LaunchRetryExhaustedOutcome",
    "_run_client_children",
    "handle_bind_failure",
    "mitmdump_log_path",
    "run_children",
    "run_client_with_retry",
    "run_prepared_client_on_local_tty",
    "start_prepared_proxy",
]


# Bounded retry budget for the allocate-→-spawn TOCTOU race. Spec
# section 147-149 prescribes 3 attempts; the failure mode is "another
# process took our port between allocate and spawn", so a fresh
# allocator call gives a different port and retries usually clear in
# 1-2 tries. The explicit-flag escape hatch covers the pathological
# case where 3 attempts are not enough.
_BIND_RETRY_ATTEMPTS = 3


# --------------------------------------------------------------------------- #
# Bind-failure detection                                                      #
# --------------------------------------------------------------------------- #


# mitmproxy prints variants like:
#   "Error starting proxy server: error while attempting to bind on
#    address ('127.0.0.1', 8787): [Errno 48] Address already in use"
# so the *signal* is the message; the *port* is whichever number sits
# nearest to it. Linux says errno 98, Darwin says 48; both surface the
# same human string. We match on the string and pluck any port-shaped
# integer from the same line — a conservative scan that won't confuse
# logs from other unrelated lines.
#
# The two `[Errno N]` needles are the OS-level fallback: Python's
# OSError repr always renders the errno that way, so even if a future
# mitmproxy strips the human-readable phrases entirely, the underlying
# OSError traceback will still carry `[Errno 48]` (Darwin) or
# `[Errno 98]` (Linux) — both are 1:1 with EADDRINUSE on their
# respective kernels, so a false positive would require an unrelated
# component logging the exact same bracketed errno on the same line as
# a port we tried, which is vanishingly unlikely.
_BIND_NEEDLES = (
    "Address already in use",
    "EADDRINUSE",
    "[Errno 48]",
    "[Errno 98]",
)
_PORT_RE = re.compile(r"\b(\d{2,5})\b")


@dataclass(frozen=True)
class ManagedClient:
    """Descriptor for the foreground interactive child process."""

    name: str
    display_name: str
    argv: list[str]
    env: dict[str, str]
    cwd: Path


class BindFailure(RuntimeError):
    """Raised by :func:`run_children` when mitmdump fails to bind a port.

    Carries the ports that were attempted on this run plus the subset
    that the log singled out as already-in-use. The caller uses
    ``failing_ports`` to decide whether the user-pinned slot is the
    culprit (fail fast) or a kernel-allocated slot (re-allocate and
    retry).
    """

    def __init__(
        self,
        *,
        proxy_port: int,
        web_port: int,
        failing_ports: tuple[int, ...],
        log_path: Path,
    ) -> None:
        self.proxy_port = proxy_port
        self.web_port = web_port
        # Whichever of (proxy_port, web_port) the log called out. Empty
        # tuple means "log said EADDRINUSE but we couldn't pin it down" —
        # treat as "both could be the cause" at the call site.
        self.failing_ports = failing_ports
        self.log_path = log_path
        super().__init__(
            f"mitmdump bind failed (proxy={proxy_port}, web={web_port}, "
            f"failing={failing_ports or 'unknown'})"
        )


@dataclass(frozen=True)
class LaunchExitOutcome:
    """Structured child lifecycle result that maps to a process exit."""

    exit_code: int
    error: str | None = None
    log_path: Path | None = None


@dataclass(frozen=True)
class LaunchBindFailureOutcome:
    """Structured child lifecycle result for retryable bind failures."""

    failure: BindFailure


@dataclass(frozen=True)
class LaunchRetryExhaustedOutcome:
    """Structured retry loop result after all bind attempts fail."""

    attempted: tuple[tuple[int, int], ...]
    proxy_port: int
    web_port: int
    proxy_user_supplied: bool
    web_user_supplied: bool


LaunchOutcome = LaunchExitOutcome | LaunchBindFailureOutcome


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
    web_port: int,
    log_path: Path,
) -> LaunchOutcome:
    failing = failing_ports_from_log(log_path, (proxy_port, web_port))
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
        error="mitmdump did not come up within 5s.",
        log_path=log_path,
    )


def format_retry_exhaustion(outcome: LaunchRetryExhaustedOutcome) -> list[str]:
    attempted_str = ", ".join(f"({p}, {w})" for p, w in outcome.attempted)
    lines = [
        f"error: could not bind ports after {_BIND_RETRY_ATTEMPTS} attempts.",
        f"  Tried (proxy, web): {attempted_str}.",
    ]

    pinned_notes: list[str] = []
    if outcome.proxy_user_supplied:
        pinned_notes.append(f"--proxy-port {outcome.proxy_port}")
    if outcome.web_user_supplied:
        pinned_notes.append(f"--web-port {outcome.web_port}")

    if pinned_notes:
        lines.extend(
            [
                f"  Pinned (held constant across all attempts): {', '.join(pinned_notes)}.",
                "Free the pinned port(s), or omit the flag to let Transport Matters allocate\n"
                "one. Check what is holding the conflicting ports "
                "(e.g. `lsof -nP -iTCP -sTCP:LISTEN`).",
            ]
        )
    else:
        lines.append(
            "Pin specific values with --proxy-port and --web-port, or check what is\n"
            "holding the conflicting ports (e.g. `lsof -nP -iTCP -sTCP:LISTEN`)."
        )
    return lines


def _raise_retry_exhausted(outcome: LaunchRetryExhaustedOutcome) -> None:
    lines = format_retry_exhaustion(outcome)
    typer.secho(lines[0], fg=typer.colors.RED, err=True)
    for line in lines[1:]:
        typer.echo(line, err=True)
    raise typer.Exit(1)


def failing_ports_from_log(log_path: Path, attempted: tuple[int, ...]) -> tuple[int, ...] | None:
    """Inspect the mitmdump log for an EADDRINUSE-shaped failure.

    Returns ``None`` if the log does not mention a bind conflict at all,
    so the caller can distinguish "real startup error" (e.g. bad
    upstream URL, missing addon) from "port stolen between allocate and
    spawn". Returns a (possibly empty) tuple of attempted ports the log
    specifically named when a bind conflict *was* detected.
    """
    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        return None
    if not any(needle in text for needle in _BIND_NEEDLES):
        return None
    # Filter to attempted ports only — the log may quote unrelated
    # numbers (errno, line counts, IP octets), but a port we tried is
    # almost certainly the failing one.
    found: list[int] = []
    for line in text.splitlines():
        if not any(needle in line for needle in _BIND_NEEDLES):
            continue
        for match in _PORT_RE.finditer(line):
            try:
                port = int(match.group(1))
            except ValueError:
                continue
            if port in attempted and port not in found:
                found.append(port)
    return tuple(found)


def handle_bind_failure(
    exc: BindFailure,
    *,
    proxy_port: int,
    web_port: int,
    proxy_user_supplied: bool,
    web_user_supplied: bool,
) -> tuple[int, int]:
    """Decide retry vs. fail-fast for a :class:`BindFailure`, return new ports.

    Returns the (proxy, web) tuple to try on the next iteration. Raises
    ``typer.Exit`` when the failure is unrecoverable (a user-pinned
    port is the one in use, or the kernel could not give us a fresh
    free pair).

    Decision rules:

    - If the log named specific failing ports and any of them is
      user-pinned, fail fast with the spec's actionable message — the
      user's choice is the broken one and silently reassigning would
      hide the bug.
    - If the log signalled EADDRINUSE but could not name the port and
      both slots are user-pinned, fail fast for the same reason.
    - Otherwise re-allocate a fresh pair via ``allocate_port_pair`` and
      overwrite only the unpinned slot(s) the log pointed at (or all
      unpinned slots if the log was port-anonymous).
    """
    failing = exc.failing_ports

    pinned_failing: list[tuple[str, int]] = []
    if failing:
        if proxy_user_supplied and proxy_port in failing:
            pinned_failing.append(("--proxy-port", proxy_port))
        if web_user_supplied and web_port in failing:
            pinned_failing.append(("--web-port", web_port))
    elif proxy_user_supplied and web_user_supplied:
        # Log said EADDRINUSE but couldn't pin the port. Both slots are
        # pinned, so we have nothing unpinned to re-allocate; treat
        # both as suspect and surface them in the error.
        pinned_failing.append(("--proxy-port", proxy_port))
        pinned_failing.append(("--web-port", web_port))
    if pinned_failing:
        msg = " and ".join(f"{flag} {p}" for flag, p in pinned_failing)
        typer.secho(
            f"error: pinned port in use: {msg}",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(
            "Free the port, or omit the flag to let Transport Matters allocate one.",
            err=True,
        )
        raise typer.Exit(2) from exc

    try:
        new_proxy, new_web = allocate_port_pair()
    except PortAllocationError as alloc_exc:
        typer.secho(f"error: {alloc_exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from alloc_exc

    if not proxy_user_supplied and (not failing or proxy_port in failing):
        proxy_port = new_proxy
    if not web_user_supplied and (not failing or web_port in failing):
        web_port = new_web
    return proxy_port, web_port


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

    Loops up to :data:`_BIND_RETRY_ATTEMPTS` attempts. Each attempt
    refreshes the manifest with the current ports, re-prints the banner
    (with a "retrying" preamble after the first), rebuilds the child
    invocations via ``build_invocation``, and calls
    :func:`_run_client_children`. On :class:`BindFailure` the retry
    decision lives in :func:`handle_bind_failure`. On exhaustion we
    surface the attempted port pairs and exit non-zero with an
    actionable message.
    """
    attempted: list[tuple[int, int]] = []
    for attempt in range(_BIND_RETRY_ATTEMPTS):
        attempted.append((proxy_port, web_port))
        write_manifest_for(proxy_port, web_port)
        if attempt > 0:
            typer.secho(
                f"retrying after bind conflict (attempt {attempt + 1}/{_BIND_RETRY_ATTEMPTS})",
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
            # On the final attempt the loop is about to exit anyway —
            # don't burn another allocator call (which could itself
            # raise PortAllocationError and hide the exhaustion message
            # the spec mandates).
            if attempt + 1 >= _BIND_RETRY_ATTEMPTS:
                break
            proxy_port, web_port = handle_bind_failure(
                exc,
                proxy_port=proxy_port,
                web_port=web_port,
                proxy_user_supplied=proxy_user_supplied,
                web_user_supplied=web_user_supplied,
            )

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
    web_port: int,
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

    # Ctrl+C during the readiness wait lands as a flag on the supervisor. Bail
    # out before spawning the client.
    if sup.received_signal is not None:
        sup.terminate_all()
        return LaunchExitOutcome(0)

    if on_backend_ready is not None:
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
