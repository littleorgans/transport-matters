"""Smoke tests for the exchanges API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import AsyncClient


class TestExchangesSmoke:
    async def test_list_empty(self, client: AsyncClient) -> None:
        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_not_found(self, client: AsyncClient) -> None:
        response = await client.get("/api/exchanges/nonexistent")
        assert response.status_code == 404
