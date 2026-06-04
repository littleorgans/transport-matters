"""Shared process supervisor data structures."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import subprocess
    import threading
    from pathlib import Path

# Sentinel returned from `wait_any`/`wait_one` when a signal, not a
# child exit, broke us out of the wait loop. Keeps the API total:
# every wait returns `(name, code)`, the caller branches on the name.
SIGNAL_EXIT = "__signal__"


@dataclass
class ManagedProcess:
    """A child process the supervisor is tracking.

    The PTY-specific fields default to `None` so every existing call
    site (inherited stdio, background log redirect) stays a plain
    `ManagedProcess`. They are populated only by the PTY spawn branch
    and consumed only by `terminate_all`.
    """

    name: str
    popen: subprocess.Popen[bytes]
    log_path: Path | None = None
    process_group: int | None = None
    # PTY state, populated iff the child was spawned with `pty=True`.
    master_fd: int | None = None
    stop_event: threading.Event | None = None
    shuttle_thread: threading.Thread | None = None
    old_termios_attrs: list[Any] | None = field(default=None)  # termios opaque list
    prev_sigwinch_handler: Any = None  # signal handler alias; see _prev_sigint note
