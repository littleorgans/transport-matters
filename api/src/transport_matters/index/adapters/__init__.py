"""Transcript adapter registry: ``harness -> adapter`` (§4). Concrete adapters are sibling modules."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from transport_matters.index.adapters.base import TranscriptAdapter

_REGISTRY: dict[str, TranscriptAdapter] = {}


def get_adapter(harness: str) -> TranscriptAdapter:
    """Return the transcript adapter for a harness (concrete adapters imported lazily to avoid a
    package-init cycle: ``base`` stays a leaf that ``sessions``/``ingest`` can import freely)."""
    if not _REGISTRY:
        from transport_matters.index.adapters.claude import ClaudeAdapter
        from transport_matters.index.adapters.codex import CodexAdapter

        _REGISTRY[ClaudeAdapter.harness] = ClaudeAdapter()
        _REGISTRY[CodexAdapter.harness] = CodexAdapter()
    adapter = _REGISTRY.get(harness)
    if adapter is None:
        raise KeyError(f"no transcript adapter registered for harness {harness!r}")
    return adapter
