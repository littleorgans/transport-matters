"""The injected post-persist tier-2 sink (§6.4 DAG-safe wiring).

The recorder (storage layer) must never import ``index`` (that back-edge is a cycle). So
tier-2 capture is wired by dependency inversion: this module holds an optional sink callable
that ``load_runtime()`` registers (closing over the ``IndexWriter`` + per-run facts), and the
recorder invokes after a successful tier-1 persist. The sink type only references storage
types, so nothing here imports ``index``.

Tier-1 is authoritative: ``emit_to_index`` swallows and logs any sink failure, so the wire
path never fails because of tier-2 (§7.1).
"""

import logging
from collections.abc import Callable

from transport_matters.storage.base import ExchangeArtifacts, IndexEntry

# A post-persist sink: hand a just-persisted exchange to tier-2. Never raises into the wire
# path (emit_to_index guards it); the enqueue must be non-blocking (the writer is async).
ExchangeSink = Callable[[IndexEntry, ExchangeArtifacts], None]

_log = logging.getLogger(__name__)
_sink: ExchangeSink | None = None


def set_exchange_sink(sink: ExchangeSink) -> None:
    """Register the tier-2 sink (called once from load_runtime, §6.4)."""
    global _sink
    _sink = sink


def clear_exchange_sink() -> None:
    """Drop the registered sink (shutdown / tests)."""
    global _sink
    _sink = None


def emit_to_index(entry: IndexEntry, artifacts: ExchangeArtifacts) -> None:
    """Hand a persisted exchange to the tier-2 sink if one is registered.

    Best-effort and non-fatal: a missing sink is a no-op, and any sink failure is logged and
    swallowed so the wire path never fails because of tier-2 (§7.1).
    """
    sink = _sink
    if sink is None:
        return
    try:
        sink(entry, artifacts)
    except Exception:
        # Non-fatal (tier-1 is authoritative), but never silent: surface at WARNING with the
        # traceback so a capture regression (silent zero-rows) cannot hide in the logs again.
        _log.warning("tier-2 index sink failed for exchange %s", entry.id, exc_info=True)
