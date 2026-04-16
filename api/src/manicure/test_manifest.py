"""Tests for the workspace manifest."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from manicure.manifest import Manifest, read, read_all, write

if TYPE_CHECKING:
    from pathlib import Path


def _sample(pid: int = 1234, slug: str = "helioy-manicure-api") -> Manifest:
    return Manifest(
        cwd="/Users/alphab/Dev/LLM/DEV/helioy/manicure/api",
        pid=pid,
        proxy_port=8787,
        web_port=8788,
        storage_dir="/Users/alphab/.manicure",
        run_id="run-001",
        started_at="2026-04-15T12:00:00+00:00",
        manicure_version="0.5.0",
        slug=slug,
        hash="deadbeef",
    )


# --------------------------------------------------------------------------- #
# Round-trip                                                                  #
# --------------------------------------------------------------------------- #


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    original = _sample()
    write(path, original)
    roundtripped = read(path)
    assert roundtripped == original


def test_write_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "deeply" / "nested" / "manifest.json"
    write(path, _sample())
    assert path.is_file()


def test_write_is_json_formatted(tmp_path: Path) -> None:
    """Readable to humans via `cat` — we indent on write."""
    path = tmp_path / "manifest.json"
    write(path, _sample())
    raw = path.read_text(encoding="utf-8")
    # Indented output has newlines; a single-line compact dump does not.
    assert "\n" in raw
    payload = json.loads(raw)
    assert payload["pid"] == 1234


# --------------------------------------------------------------------------- #
# Tolerating bad input                                                        #
# --------------------------------------------------------------------------- #


def test_read_missing_file_returns_none(tmp_path: Path) -> None:
    assert read(tmp_path / "no-such-file.json") is None


def test_read_malformed_json_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert read(path) is None


def test_read_non_object_json_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert read(path) is None


def test_read_schema_mismatch_returns_none(tmp_path: Path) -> None:
    """Old-version / foreign manifests with unknown fields are treated
    as stale rather than crashing the caller."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"cwd": "/tmp"}), encoding="utf-8")
    assert read(path) is None


# --------------------------------------------------------------------------- #
# read_all                                                                    #
# --------------------------------------------------------------------------- #


def test_read_all_missing_root_returns_empty(tmp_path: Path) -> None:
    assert read_all(tmp_path / "does-not-exist") == []


def test_read_all_scans_slug_hash_layout(tmp_path: Path) -> None:
    a = tmp_path / "slug-a" / "hash-a" / "manifest.json"
    b = tmp_path / "slug-b" / "hash-b" / "manifest.json"
    write(a, _sample(pid=1, slug="slug-a"))
    write(b, _sample(pid=2, slug="slug-b"))
    found = read_all(tmp_path)
    pids = sorted(m.pid for m in found)
    assert pids == [1, 2]


def test_read_all_skips_malformed(tmp_path: Path) -> None:
    good = tmp_path / "slug-a" / "hash-a" / "manifest.json"
    bad = tmp_path / "slug-b" / "hash-b" / "manifest.json"
    write(good, _sample(pid=1, slug="slug-a"))
    bad.parent.mkdir(parents=True)
    bad.write_text("{garbage", encoding="utf-8")
    found = read_all(tmp_path)
    assert len(found) == 1
    assert found[0].slug == "slug-a"


def test_read_all_ignores_files_outside_expected_layout(tmp_path: Path) -> None:
    # A manifest-looking file at the wrong depth must not be picked up.
    stray = tmp_path / "manifest.json"
    write(stray, _sample())
    # Valid manifest at the expected depth.
    correct = tmp_path / "slug" / "hash" / "manifest.json"
    write(correct, _sample(pid=99, slug="slug"))
    found = read_all(tmp_path)
    assert [m.pid for m in found] == [99]
