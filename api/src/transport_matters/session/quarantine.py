"""Classification and limits for transcript dead-letter quarantine."""

from __future__ import annotations

from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Literal

import psycopg
from psycopg_pool import PoolTimeout

POISON_SQLSTATE_CLASSES = frozenset({"22", "54"})
TRANSIENT_SQLSTATE_CLASSES = frozenset({"08", "53", "57", "58", "40", "55"})
QUARANTINE_MAX_ATTEMPTS = 5
DEAD_LETTER_RAW_MAX_BYTES = 64 * 1024

QuarantineKind = Literal["poison", "transient", "other"]


def classify(exc: BaseException) -> QuarantineKind:
    """Classify a failure for retry versus quarantine policy."""
    if isinstance(exc, (PoolTimeout, FutureTimeoutError)):
        return "transient"
    if not isinstance(exc, psycopg.Error):
        return "transient"
    sqlstate = exc.sqlstate
    if sqlstate is None:
        if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
            return "transient"
        return "other"
    state_class = sqlstate[:2]
    if state_class in POISON_SQLSTATE_CLASSES:
        return "poison"
    if state_class in TRANSIENT_SQLSTATE_CLASSES:
        return "transient"
    return "other"
