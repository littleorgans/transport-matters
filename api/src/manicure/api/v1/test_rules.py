"""Tests for the rules API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from manicure.main import create_app
from manicure.storage import init_storage, reset_storage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _setup_storage(tmp_path: Path) -> Generator[None]:
    """Initialise storage with a temp dir before each test."""
    reset_storage()
    init_storage(root=tmp_path)
    yield
    reset_storage()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


_RULE_BODY = {
    "name": "Strip MCP tools",
    "scope": {"global": True},
    "action": "strip_tools",
    "params": {"prefix": "mcp_"},
}


class TestListRules:
    async def test_list_empty(self, client: AsyncClient) -> None:
        response = await client.get("/api/rules")
        assert response.status_code == 200
        assert response.json() == []


class TestCreateRule:
    async def test_create_rule(self, client: AsyncClient) -> None:
        response = await client.post("/api/rules", json=_RULE_BODY)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Strip MCP tools"
        assert data["action"] == "strip_tools"
        assert data["enabled"] is True
        assert data["applied_count"] == 0
        assert "id" in data


class TestCreateAndList:
    async def test_create_and_list(self, client: AsyncClient) -> None:
        await client.post("/api/rules", json=_RULE_BODY)
        response = await client.get("/api/rules")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Strip MCP tools"


class TestPatchRule:
    async def test_patch_enabled(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/rules", json=_RULE_BODY)
        rule_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/rules/{rule_id}", json={"enabled": False}
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["enabled"] is False

    async def test_patch_not_found(self, client: AsyncClient) -> None:
        response = await client.patch("/api/rules/nonexistent", json={"enabled": False})
        assert response.status_code == 404


class TestDeleteRule:
    async def test_delete_rule(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/rules", json=_RULE_BODY)
        rule_id = create_resp.json()["id"]

        del_resp = await client.delete(f"/api/rules/{rule_id}")
        assert del_resp.status_code == 204

        list_resp = await client.get("/api/rules")
        assert list_resp.json() == []

    async def test_delete_not_found(self, client: AsyncClient) -> None:
        response = await client.delete("/api/rules/nonexistent")
        assert response.status_code == 404
