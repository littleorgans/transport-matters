"""Public process supervisor facade.

The implementation is split by responsibility across sibling modules,
while this module preserves the historical import surface used by the CLI
and colocated tests.
"""

import fcntl as fcntl
import os as os
import pty as pty
import select as select
import signal as signal
import subprocess as subprocess
import sys as sys
import termios as termios
import threading as threading

from transport_matters.supervisor_core import ProcessSupervisor as ProcessSupervisor
from transport_matters.supervisor_models import SIGNAL_EXIT as SIGNAL_EXIT
from transport_matters.supervisor_models import ManagedProcess as ManagedProcess
from transport_matters.supervisor_pty import _install_parent_cbreak as _install_parent_cbreak
from transport_matters.supervisor_pty import _pty_shuttle as _pty_shuttle

__all__ = [
    "SIGNAL_EXIT",
    "ManagedProcess",
    "ProcessSupervisor",
    "_install_parent_cbreak",
    "_pty_shuttle",
]
