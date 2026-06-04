"""The injected post-persist sink registry: fires, no-ops when empty, swallows failures (§7.1)."""

from typing import TYPE_CHECKING

from transport_matters.storage.exchange_sink import (
    clear_exchange_sink,
    emit_to_index,
    set_exchange_sink,
)
from transport_matters.storage.test_exchange_support import (
    make_artifacts,
    make_index_entry,
    make_request_ir,
)

if TYPE_CHECKING:
    from transport_matters.storage.base import ExchangeArtifacts, IndexEntry


def _exchange() -> tuple[IndexEntry, ExchangeArtifacts]:
    return make_index_entry(), make_artifacts(make_request_ir())


class TestExchangeSink:
    def test_emit_invokes_registered_sink(self) -> None:
        seen: list[str] = []
        set_exchange_sink(lambda entry, _artifacts: seen.append(entry.id))
        try:
            entry, artifacts = _exchange()
            emit_to_index(entry, artifacts)
        finally:
            clear_exchange_sink()
        assert seen == ["ex1"]

    def test_emit_without_sink_is_noop(self) -> None:
        clear_exchange_sink()
        entry, artifacts = _exchange()
        emit_to_index(entry, artifacts)  # no sink registered -> no error

    def test_sink_failure_is_swallowed(self) -> None:
        def boom(entry: IndexEntry, artifacts: ExchangeArtifacts) -> None:
            raise RuntimeError("tier-2 down")

        set_exchange_sink(boom)
        try:
            entry, artifacts = _exchange()
            emit_to_index(entry, artifacts)  # must NOT propagate (tier-1 first)
        finally:
            clear_exchange_sink()
