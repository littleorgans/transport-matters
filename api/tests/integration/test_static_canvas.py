from typing import TYPE_CHECKING

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from transport_matters.main import SpaStaticFiles

if TYPE_CHECKING:
    from pathlib import Path


async def test_canvas_route_uses_spa_fallback(tmp_path: Path) -> None:
    app = spa_test_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/canvas")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<html" in response.text.lower()


async def test_missing_asset_does_not_use_spa_fallback(tmp_path: Path) -> None:
    app = spa_test_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/assets/not-present.js")

    assert response.status_code == 404


async def test_unknown_api_path_does_not_use_spa_fallback(tmp_path: Path) -> None:
    app = spa_test_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/not-present")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "<html" not in response.text.lower()


def spa_test_app(tmp_path: Path) -> FastAPI:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html><body>app</body></html>", encoding="utf-8")
    app = FastAPI()
    app.mount("/", SpaStaticFiles(directory=tmp_path, html=True), name="www")
    return app
