"""Free-port allocation for Transport Matters launches.

Exposes :func:`allocate_port_pair`, used by ``start`` when the user
omits ``--proxy-port`` / ``--web-port``. The kernel picks two distinct
free ports via ``bind(("127.0.0.1", 0))`` on two simultaneously open
sockets — that guarantees uniqueness within a single allocation, with
no inter-process coordination.

Two intentional non-features:

- We do not "reserve" the ports. Between this call and mitmdump's own
  ``bind`` there is a TOCTOU window where another process can take one
  of the chosen ports. Spec accepts that race; mitmdump will exit and
  the user can retry or pass ``--proxy-port``.

- We do not coordinate across concurrent launches. Two
  callers in the same millisecond may both ask the kernel "give me a
  free port" and get the same answer; the loser of the eventual bind
  race retries.

The retry loop here only guards the (rare) case where ``bind`` itself
fails — typically only when local ports are actually exhausted — and
the (theoretically impossible) case where the kernel double-assigns
within one allocation.
"""

from __future__ import annotations

import socket

__all__ = ["PortAllocationError", "allocate_port_pair"]


_DEFAULT_ATTEMPTS = 3


class PortAllocationError(RuntimeError):
    """Raised when the OS could not give us two free TCP ports."""


def allocate_port_pair(*, attempts: int = _DEFAULT_ATTEMPTS) -> tuple[int, int]:
    """Return two distinct free TCP ports on 127.0.0.1.

    Opens two listening sockets bound to port 0 (kernel-assigned),
    reads ``getsockname()`` on each, closes both, and returns the
    pair. Both sockets are open at the same time so the kernel can't
    hand out the same port twice within one allocation.

    Retries up to *attempts* times if either ``bind`` raises ``OSError``
    (effectively only when local ports are exhausted) or — defensively —
    if both ports come back equal. After the budget is exhausted, raises
    :class:`PortAllocationError` with an actionable message.
    """
    last_exc: OSError | None = None
    for _ in range(attempts):
        try:
            with (
                socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s1,
                socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2,
            ):
                s1.bind(("127.0.0.1", 0))
                s2.bind(("127.0.0.1", 0))
                p1 = s1.getsockname()[1]
                p2 = s2.getsockname()[1]
        except OSError as exc:
            last_exc = exc
            continue
        if p1 != p2:
            return p1, p2
        # Defensive: kernel double-assigned across two open sockets.
        # Should never happen on Linux/Darwin; retry for completeness.

    msg = (
        f"could not allocate a free TCP port pair after {attempts} attempts. "
        "Pass --proxy-port and --web-port explicitly."
    )
    if last_exc is not None:
        raise PortAllocationError(msg) from last_exc
    raise PortAllocationError(msg)
