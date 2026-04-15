"""Port-probing helpers used by `start` and `doctor`."""

from __future__ import annotations

import socket
import time

import typer


def validate_port_option(value: int | None) -> int | None:
    """Typer callback: reject ports outside ``[1, 65535]``.

    Catches three failure modes the kernel/socket layer would otherwise
    surface as either an unhandled ``OverflowError`` (negative or
    >65535) or as a silently-broken invocation (``--proxy-port 0``
    passes 0 to mitmdump and into the injected system-prompt URL,
    yielding ``http://localhost:0`` — a URL the model can't use).

    Omitting the flag (``value is None``) means "let manicure
    allocate"; we let that through unchanged.
    """
    if value is None:
        return None
    if value < 1 or value > 65535:
        raise typer.BadParameter(
            f"port must be in 1..65535, got {value}. "
            "Omit the flag to let manicure allocate a free port."
        )
    return value


def _port_in_use(port: int) -> bool:
    """Return True if *port* on localhost has an active listener.

    We probe with ``connect_ex`` instead of ``bind``. Rebinding can fail
    transiently after a recent shutdown on macOS because the old socket
    left connections in ``TIME_WAIT`` even though no process is actually
    listening anymore. For CLI preflight we only care whether a new
    client could connect right now.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_port_ready(
    host: str, port: int, *, timeout: float = 5.0, interval: float = 0.1
) -> bool:
    """Poll a TCP port until it accepts connections, or return False on timeout.

    We poll (not sleep) because mitmdump's startup time varies with the
    machine: fast on a dev laptop, noticeably slower on CI. A fixed sleep
    either wastes time on fast systems or races on slow ones. Polling
    returns as soon as the socket is ready.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(interval)
    return False
