"""Tests for the exchanges list endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from httpx import ASGITransport, AsyncClient

from manicure import config
from manicure.main import create_app

from .test_exchanges_support import make_index_entry

if TYPE_CHECKING:
    import pytest


class TestListExchanges:
    async def test_list_after_write_for_current_run(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from manicure.storage import get_storage

        monkeypatch.setenv("MANICURE_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        entry = make_index_entry(run_id="run-current")
        await storage.append_index(entry)

        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "ex-001"

    async def test_list_hides_other_runs_by_default(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from manicure.storage import get_storage

        monkeypatch.setenv("MANICURE_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        await storage.append_index(make_index_entry("ex-old", run_id="run-old"))
        await storage.append_index(make_index_entry("ex-new", run_id="run-current"))

        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        data = response.json()
        assert [row["id"] for row in data] == ["ex-new"]

    async def test_list_include_history_returns_all_runs(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from manicure.storage import get_storage

        monkeypatch.setenv("MANICURE_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        await storage.append_index(make_index_entry("ex-old", run_id="run-old"))
        await storage.append_index(make_index_entry("ex-new", run_id="run-current"))

        response = await client.get("/api/exchanges?include_history=true")
        assert response.status_code == 200
        data = response.json()
        assert [row["id"] for row in data] == ["ex-old", "ex-new"]

    async def test_list_mixed_providers_respects_run_scope_and_history(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from manicure.storage import get_storage

        monkeypatch.setenv("MANICURE_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        await storage.append_index(make_index_entry("anth-old", run_id="run-old"))
        await storage.append_index(
            make_index_entry("codex-old", run_id="run-old").model_copy(
                update={
                    "provider": "codex",
                    "model": "codex/gpt-5-codex",
                }
            )
        )
        await storage.append_index(
            make_index_entry("anth-current", run_id="run-current")
        )
        await storage.append_index(
            make_index_entry("codex-current", run_id="run-current").model_copy(
                update={
                    "provider": "codex",
                    "model": "codex/gpt-5-codex",
                }
            )
        )

        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        data = response.json()
        assert [(row["id"], row["provider"]) for row in data] == [
            ("anth-current", "anthropic"),
            ("codex-current", "codex"),
        ]

        history = await client.get("/api/exchanges?include_history=true")
        assert history.status_code == 200
        history_data = history.json()
        assert [
            (row["id"], row["run_id"], row["provider"]) for row in history_data
        ] == [
            ("anth-old", "run-old", "anthropic"),
            ("codex-old", "run-old", "codex"),
            ("anth-current", "run-current", "anthropic"),
            ("codex-current", "run-current", "codex"),
        ]


class TestListExchangesStorageFailure:
    async def test_storage_exception_returns_500(self) -> None:
        """When storage.read_index() raises, the endpoint returns 500 with a structured error."""
        from unittest.mock import AsyncMock

        from manicure.storage import get_storage

        broken_backend = AsyncMock()
        broken_backend.read_index.side_effect = RuntimeError("disk on fire")

        app = create_app()
        app.dependency_overrides[get_storage] = lambda: broken_backend

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/exchanges")

        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert "Failed to read exchange index" in data["detail"]
