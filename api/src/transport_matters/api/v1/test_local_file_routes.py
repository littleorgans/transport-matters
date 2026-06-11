"""Tests for the local-file resource content route.

The route is deliberately unguarded like list_runs (run_routes.py): same-origin
GET fetches carry no Origin header, so the terminal-WS origin guard would 403
the legitimate caller. The no-header requests below ARE the real app path.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from transport_matters import config
from transport_matters.api.v1 import local_file_routes
from transport_matters.main import create_app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    config.get_settings.cache_clear()
    return TestClient(create_app())


def _get(client: TestClient, path: str) -> dict[str, object]:
    response = client.get("/api/local-file", params={"path": path})
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


def test_png_returns_image_content_without_origin_header(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "shot.png"
    target.write_bytes(PNG_BYTES)
    with _client(monkeypatch, tmp_path) as client:
        body = _get(client, str(target))
    assert body["kind"] == "image"
    assert body["bytesBase64"] == base64.b64encode(PNG_BYTES).decode("ascii")
    assert body["mediaType"] == "image/png"
    assert body["title"] == "shot.png"


def test_markdown_returns_text_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("# hello\n", encoding="utf-8")
    with _client(monkeypatch, tmp_path) as client:
        body = _get(client, str(target))
    assert body["kind"] == "text"
    assert body["text"] == "# hello\n"


def test_json_returns_json_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    target.write_text('{"a": 1}', encoding="utf-8")
    with _client(monkeypatch, tmp_path) as client:
        body = _get(client, str(target))
    assert body["kind"] == "json"
    assert body["value"] == {"a": 1}


def test_missing_file_returns_typed_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _client(monkeypatch, tmp_path) as client:
        body = _get(client, str(tmp_path / "gone.png"))
    assert body["kind"] == "missing"
    assert body["reason"] == "not-found"


def test_directory_returns_typed_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with _client(monkeypatch, tmp_path) as client:
        body = _get(client, str(tmp_path))
    assert body["kind"] == "missing"
    assert body["reason"] == "unsupported"


def test_relative_path_returns_typed_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _client(monkeypatch, tmp_path) as client:
        body = _get(client, "relative/shot.png")
    assert body["kind"] == "missing"
    assert body["reason"] == "unsupported"


def test_oversized_file_returns_too_large(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "huge.bin"
    target.write_bytes(b"x" * 32)
    monkeypatch.setattr(local_file_routes, "LOCAL_FILE_BYTE_LIMIT", 16)
    with _client(monkeypatch, tmp_path) as client:
        body = _get(client, str(target))
    assert body["kind"] == "missing"
    assert body["reason"] == "too-large"
