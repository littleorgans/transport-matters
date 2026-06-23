"""Port-probing helpers used by `start` and `doctor`."""

import socket

import typer

from transport_matters.loopback import LOOPBACK_HOST, loopback_http_url, wait_for_port_ready

__all__ = [
    "LOOPBACK_HOST",
    "loopback_http_url",
    "port_in_use",
    "raise_port_in_use",
    "validate_port_option",
    "wait_for_port_ready",
]


def validate_port_option(value: int | None) -> int | None:
    """Typer callback: reject ports outside ``[1, 65535]``.

    Catches three failure modes the kernel/socket layer would otherwise
    surface as either an unhandled ``OverflowError`` (negative or
    >65535) or as a silently-broken invocation (``--proxy-port 0``
    passes 0 to mitmdump and into the injected system-prompt URL,
    yielding ``http://127.0.0.1:0`` — a URL the model can't use).

    Omitting the flag (``value is None``) means "let Transport Matters
    allocate"; we let that through unchanged.
    """
    if value is None:
        return None
    if value < 1 or value > 65535:
        raise typer.BadParameter(
            f"port must be in 1..65535, got {value}. "
            "Omit the flag to let Transport Matters allocate a free port."
        )
    return value


def port_in_use(port: int) -> bool:
    """Return True if *port* on the IPv4 loopback has an active listener.

    We probe with ``connect_ex`` instead of ``bind``. Rebinding can fail
    transiently after a recent shutdown on macOS because the old socket
    left connections in ``TIME_WAIT`` even though no process is actually
    listening anymore. For CLI preflight we only care whether a new
    client could connect right now.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def raise_port_in_use(label: str, flag: str, port: int) -> None:
    """Emit the standard pinned-port error and exit."""
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
