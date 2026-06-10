"""Domain types for the Transport Matters launch lifecycle.

Pure data carriers shared by the launch supervisor (:mod:`runner`) and
the bind-failure policy (:mod:`bind_failure`). The managed-client
descriptor lives with the lifecycle in :mod:`runner`; the bind
exception and the structured child-lifecycle results live here so both
modules can depend on them without an import cycle.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "BindFailure",
    "LaunchBindFailureOutcome",
    "LaunchExitOutcome",
    "LaunchOutcome",
    "LaunchRetryExhaustedOutcome",
]


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
        web_port: int | None,
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
    web_port: int | None
    proxy_user_supplied: bool
    web_user_supplied: bool


LaunchOutcome = LaunchExitOutcome | LaunchBindFailureOutcome
