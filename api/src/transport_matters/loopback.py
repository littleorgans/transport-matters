"""Loopback URL and TCP readiness helpers."""

from __future__ import annotations

import socket
import time

LOOPBACK_HOST = "127.0.0.1"


def loopback_http_url(port: int) -> str:
    """Return the explicit IPv4 loopback URL for *port*."""
    return f"http://{LOOPBACK_HOST}:{port}"


def wait_for_port_ready(
    host: str, port: int, *, timeout: float = 5.0, interval: float = 0.1
) -> bool:
    """Poll a TCP port until it accepts connections, or return False on timeout."""
    # Poll instead of sleeping because mitmdump startup time varies. A fixed sleep
    # either wastes time or races the server.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(interval)
    return False
