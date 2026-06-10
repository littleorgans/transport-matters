"""EADDRINUSE detection and the allocate-→-spawn retry policy.

mitmdump can fail to bind a port when another process grabs it between
our allocate and spawn. This module owns that concern end to end:
detect the bind conflict in the mitmdump log
(:func:`failing_ports_from_log`), decide retry-vs-fail-fast for a
:class:`BindFailure` (:func:`handle_bind_failure`), and format the
retry-exhaustion message the launch supervisor prints on give-up
(:func:`format_retry_exhaustion`).
"""

import re
from typing import TYPE_CHECKING

import typer

from .ports import PortAllocationError, allocate_port_pair

if TYPE_CHECKING:
    from pathlib import Path

    from .launch_outcomes import BindFailure, LaunchRetryExhaustedOutcome

__all__ = [
    "BIND_RETRY_ATTEMPTS",
    "failing_ports_from_log",
    "format_retry_exhaustion",
    "handle_bind_failure",
]


# Bounded retry budget for the allocate-→-spawn TOCTOU race. Spec
# section 147-149 prescribes 3 attempts; the failure mode is "another
# process took our port between allocate and spawn", so a fresh
# allocator call gives a different port and retries usually clear in
# 1-2 tries. The explicit-flag escape hatch covers the pathological
# case where 3 attempts are not enough.
BIND_RETRY_ATTEMPTS = 3


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
    web_port: int | None,
    proxy_user_supplied: bool,
    web_user_supplied: bool,
) -> tuple[int, int | None]:
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
        if web_port is not None and web_user_supplied and web_port in failing:
            pinned_failing.append(("--web-port", web_port))
    elif proxy_user_supplied and (web_port is None or web_user_supplied):
        # Log said EADDRINUSE but couldn't pin the port. Both slots are
        # pinned, so we have nothing unpinned to re-allocate; treat
        # both as suspect and surface them in the error.
        pinned_failing.append(("--proxy-port", proxy_port))
        if web_port is not None:
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
    if web_port is not None and not web_user_supplied and (not failing or web_port in failing):
        web_port = new_web
    return proxy_port, web_port


def format_retry_exhaustion(outcome: LaunchRetryExhaustedOutcome) -> list[str]:
    attempted_str = ", ".join(f"({p}, {w})" for p, w in outcome.attempted)
    lines = [
        f"error: could not bind ports after {BIND_RETRY_ATTEMPTS} attempts.",
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
