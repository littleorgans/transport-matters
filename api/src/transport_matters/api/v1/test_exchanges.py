"""Smoke tests for the exchanges API endpoints."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import AsyncClient


class TestExchangesSmoke:
    async def test_list_empty(self, client: AsyncClient) -> None:
        response = await client.get("/v1/runs/run-current/exchanges")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_not_found(self, client: AsyncClient) -> None:
        response = await client.get("/v1/runs/run-current/exchanges/nonexistent")
        assert response.status_code == 404

    async def test_unknown_run_returns_404(self, client: AsyncClient) -> None:
        response = await client.get("/v1/runs/unknown-run/exchanges")
        assert response.status_code == 404

    async def test_global_routes_are_removed(self, client: AsyncClient) -> None:
        response = await client.get("/api/exchanges")
        assert response.status_code == 404
