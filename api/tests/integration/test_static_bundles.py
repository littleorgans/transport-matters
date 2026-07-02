"""Two-bundle static serving, validated against the REAL built artifacts.

The inspector bundle (base "/") lives in transport_matters/www; the canvas
bundle (base "/canvas") lives in transport_matters/canvas. These tests mount
them through the same code path production uses (`mount_frontend_bundles`),
so mount order and SPA fallback behavior are exercised as deployed, not
reconstructed. Skipped when the bundles are absent: run `just build` first.
"""

from pathlib import Path

import pytest
import transport_matters
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from transport_matters.main import mount_frontend_bundles

_PACKAGE_DIR = Path(transport_matters.__file__).parent
WWW_DIR = _PACKAGE_DIR / "www"
CANVAS_DIR = _PACKAGE_DIR / "canvas"

pytestmark = pytest.mark.skipif(
    not ((WWW_DIR / "index.html").is_file() and (CANVAS_DIR / "index.html").is_file()),
    reason=(
        "requires both built bundles: run `just build` "
        "(or `pnpm --filter @tm/inspector build && pnpm --filter @tm/canvas build`)"
    ),
)


def bundle_app() -> FastAPI:
    app = FastAPI()
    mount_frontend_bundles(app)
    return app


async def fetch(path: str) -> tuple[int, str, str]:
    app = bundle_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        response = await client.get(path)
    return response.status_code, response.headers.get("content-type", ""), response.text


def inspector_index() -> str:
    return (WWW_DIR / "index.html").read_text(encoding="utf-8")


def canvas_index() -> str:
    return (CANVAS_DIR / "index.html").read_text(encoding="utf-8")


def first_asset(bundle_dir: Path) -> str:
    assets = sorted(path.name for path in (bundle_dir / "assets").iterdir() if path.is_file())
    assert assets, f"{bundle_dir}/assets is empty"
    return assets[0]


async def test_root_serves_the_inspector_bundle() -> None:
    status, content_type, text = await fetch("/")

    assert status == 200
    assert "text/html" in content_type
    assert text == inspector_index()


async def test_unknown_route_falls_back_to_the_inspector_spa() -> None:
    status, _, text = await fetch("/some/client/route")

    assert status == 200
    assert text == inspector_index()


async def test_canvas_serves_the_canvas_bundle() -> None:
    status, content_type, text = await fetch("/canvas")

    assert status == 200
    assert "text/html" in content_type
    assert text == canvas_index()


async def test_canvas_subpath_falls_back_to_the_canvas_spa() -> None:
    status, _, text = await fetch("/canvas/deep/link")

    assert status == 200
    assert text == canvas_index()


async def test_canvas_lab_serves_the_canvas_bundle() -> None:
    # /canvas-lab is a canvas SPA page (RouteSwitcher and the launcher
    # navigate to it; the desktop shell whitelists it) that sits outside the
    # /canvas mount path. It must never fall through to the inspector.
    status, _, text = await fetch("/canvas-lab")

    assert status == 200
    assert text == canvas_index()


def test_the_two_bundles_are_distinct() -> None:
    assert inspector_index() != canvas_index()
    assert "/canvas/assets/" in canvas_index()
    assert "/canvas/assets/" not in inspector_index()


async def test_missing_inspector_asset_404s_not_spa_fallback() -> None:
    status, _, text = await fetch("/assets/nonexistent.js")

    assert status == 404
    assert "<html" not in text.lower()


async def test_missing_canvas_asset_404s_not_spa_fallback() -> None:
    status, _, text = await fetch("/canvas/assets/nonexistent.js")

    assert status == 404
    assert "<html" not in text.lower()


async def test_real_assets_serve_from_each_bundle() -> None:
    inspector_status, _, _ = await fetch(f"/assets/{first_asset(WWW_DIR)}")
    canvas_status, _, _ = await fetch(f"/canvas/assets/{first_asset(CANVAS_DIR)}")

    assert inspector_status == 200
    assert canvas_status == 200


async def test_unknown_api_path_does_not_use_spa_fallback() -> None:
    status, content_type, text = await fetch("/api/not-present")

    assert status == 404
    assert content_type.startswith("application/json")
    assert "<html" not in text.lower()
