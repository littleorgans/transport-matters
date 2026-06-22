from __future__ import annotations

import pytest

from transport_matters.session.pool import create_async_pool


def test_create_async_pool_rejects_non_test_database_under_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_create_async_pool_guard")

    with pytest.raises(RuntimeError, match="refusing to open non-test session store"):
        create_async_pool("postgresql://tm:tm@localhost:55432/transport_matters")
