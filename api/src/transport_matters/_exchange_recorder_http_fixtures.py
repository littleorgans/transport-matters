from typing import TYPE_CHECKING

import pytest

from transport_matters.test_exchange_recorder_support import (
    reset_exchange_recorder_runtime_state,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_runtime_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    yield from reset_exchange_recorder_runtime_state(tmp_path, monkeypatch)
