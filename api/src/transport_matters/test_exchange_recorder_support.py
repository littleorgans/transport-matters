from typing import TYPE_CHECKING, Any

from transport_matters import broadcast, config
from transport_matters.storage import init_storage, reset_storage
from transport_matters.track_manager import get_track_manager

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


def reset_exchange_recorder_runtime_state(
    tmp_path: Path,
    monkeypatch: Any,
) -> Generator[None]:
    broadcast._subscribers.clear()
    broadcast._next_id = 0
    reset_storage()
    init_storage(root=tmp_path)
    get_track_manager()._runs.clear()
    monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-http")
    config.get_settings.cache_clear()
    yield
    broadcast._subscribers.clear()
    broadcast._next_id = 0
    reset_storage()
    get_track_manager()._runs.clear()
    config.get_settings.cache_clear()
