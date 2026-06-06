"""Optional post-persist exchange sink.

The recorder (storage layer) owns wire persistence and does not import higher-level packages.
This module holds an optional dependency-inverted callback for consumers that need post-store
exchange notifications.

Tier-1 is authoritative: ``emit_to_index`` swallows and logs any sink failure, so the wire
path never fails because of an observer (§7.1).
"""

import logging
from collections.abc import Callable

from transport_matters.storage.base import ExchangeArtifacts, IndexEntry

# A post-persist sink: hand a just-persisted exchange to an observer. Never raises into the
# wire path (emit_to_index guards it); implementations should be non-blocking.
ExchangeSink = Callable[[IndexEntry, ExchangeArtifacts], None]

_log = logging.getLogger(__name__)
_sink: ExchangeSink | None = None


def set_exchange_sink(sink: ExchangeSink) -> None:
    """Register the post-persist exchange sink."""
    global _sink
    _sink = sink


def clear_exchange_sink() -> None:
    """Drop the registered sink (shutdown / tests)."""
    global _sink
    _sink = None


def emit_to_index(entry: IndexEntry, artifacts: ExchangeArtifacts) -> None:
    """Hand a persisted exchange to the optional sink if one is registered.

    Best-effort and non-fatal: a missing sink is a no-op, and any sink failure is logged and
    swallowed so the wire path never fails because of an observer (§7.1).
    """
    sink = _sink
    if sink is None:
        return
    try:
        sink(entry, artifacts)
    except Exception:
        # Non-fatal (tier-1 is authoritative), but never silent.
        _log.warning("exchange sink failed for exchange %s", entry.id, exc_info=True)
