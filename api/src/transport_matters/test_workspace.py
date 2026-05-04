"""Tests for workspace identity."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from transport_matters.workspace import (
    WorkspaceId,
    workspace_id,
    workspace_root,
    workspace_storage,
)

# --------------------------------------------------------------------------- #
# Slug derivation                                                             #
# --------------------------------------------------------------------------- #


def test_slug_matches_last_three_segments() -> None:
    wid = workspace_id(Path("/Users/alphab/Dev/LLM/DEV/helioy/manicure/api"))
    assert wid.slug == "helioy-manicure-api"


def test_slug_preserves_underscores() -> None:
    wid = workspace_id(Path("/project/my_repo/api"))
    assert wid.slug == "project-my_repo-api"


def test_slug_preserves_existing_dashes() -> None:
    wid = workspace_id(Path("/my-org/some-repo/api"))
    assert wid.slug == "my-org-some-repo-api"


def test_slug_collapses_illegal_chars_to_dash() -> None:
    wid = workspace_id(Path("/my/weird path/with!@#chars"))
    assert wid.slug == "my-weird-path-with-chars"
    assert " " not in wid.slug
    assert "!" not in wid.slug


def test_slug_for_root_is_literal_root() -> None:
    assert workspace_id(Path("/")).slug == "root"


def test_slug_for_single_segment() -> None:
    assert workspace_id(Path("/foo")).slug == "foo"


def test_slug_for_two_segments() -> None:
    assert workspace_id(Path("/foo/bar")).slug == "foo-bar"


def test_slug_is_lowercased() -> None:
    wid = workspace_id(Path("/ORG/Repo/API"))
    assert wid.slug == "org-repo-api"


def test_slug_caps_at_40_chars() -> None:
    # Three 30-char segments → 90 raw chars + 2 dashes = 92; cap → 40.
    wid = workspace_id(Path("/" + "/".join(["a" * 30, "b" * 30, "c" * 30])))
    assert len(wid.slug) <= 40
    # Left-truncation keeps the leaf (c-run) intact at the right end.
    assert wid.slug.endswith("c" * 30)


def test_slug_is_never_empty_after_sanitisation() -> None:
    # Path segments consisting entirely of illegal chars collapse to dashes
    # and get stripped. The fallback is "root".
    wid = workspace_id(Path("/!!!/???/***"))
    assert wid.slug == "root"


# --------------------------------------------------------------------------- #
# Hash derivation                                                             #
# --------------------------------------------------------------------------- #


def test_hash_is_8_hex_chars() -> None:
    wid = workspace_id(Path("/tmp/example"))
    assert len(wid.hash) == 8
    assert all(c in "0123456789abcdef" for c in wid.hash)


def test_hash_is_stable_across_calls(tmp_path: Path) -> None:
    assert workspace_id(tmp_path) == workspace_id(tmp_path)


def test_hash_differs_for_distinct_paths() -> None:
    a = workspace_id(Path("/tmp/aaa"))
    b = workspace_id(Path("/tmp/bbb"))
    assert a.hash != b.hash


def test_hash_ignores_unresolved_symlink_path(tmp_path: Path) -> None:
    """Canonicalisation happens before hashing, so a symlink and its
    target resolve to the same hash."""
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    assert workspace_id(link).hash == workspace_id(target).hash


# --------------------------------------------------------------------------- #
# Canonicalisation                                                            #
# --------------------------------------------------------------------------- #


def test_canonical_root_follows_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    assert workspace_id(link).root == target.resolve()


def test_canonical_root_accepts_nonexistent_path(tmp_path: Path) -> None:
    phantom = tmp_path / "does-not-exist" / "nested"
    wid = workspace_id(phantom)
    assert wid.root == phantom


# --------------------------------------------------------------------------- #
# WorkspaceId shape                                                           #
# --------------------------------------------------------------------------- #


def test_workspace_id_is_frozen() -> None:
    wid = workspace_id(Path("/tmp"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        wid.slug = "clobber"  # type: ignore[misc]


def test_workspace_id_equality_is_value_based() -> None:
    a = workspace_id(Path("/tmp/example"))
    b = workspace_id(Path("/tmp/example"))
    assert a == b
    assert hash(a) == hash(b)


def test_workspace_id_is_hashable() -> None:
    # We rely on this so workspace ids can key dicts / populate sets.
    seen: set[WorkspaceId] = set()
    seen.add(workspace_id(Path("/tmp/a")))
    seen.add(workspace_id(Path("/tmp/a")))
    seen.add(workspace_id(Path("/tmp/b")))
    assert len(seen) == 2


# --------------------------------------------------------------------------- #
# workspace_root                                                              #
# --------------------------------------------------------------------------- #


def test_workspace_root_composes_slug_and_hash() -> None:
    cwd = Path("/tmp/project/api")
    wid = workspace_id(cwd)
    assert (
        workspace_root(cwd)
        == Path.home() / ".manicure" / "workspaces" / wid.slug / wid.hash
    )


def test_workspace_root_does_not_create_directory(tmp_path: Path) -> None:
    cwd = tmp_path / "myproj"
    cwd.mkdir()
    root = workspace_root(cwd)
    assert not root.exists()


# --------------------------------------------------------------------------- #
# workspace_storage                                                           #
# --------------------------------------------------------------------------- #


def test_workspace_storage_matches_workspace_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same slug/hash triple as the read-only :func:`workspace_root`."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert workspace_storage(cwd) == workspace_root(cwd)


def test_workspace_storage_creates_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cwd = tmp_path / "project"
    cwd.mkdir()
    path = workspace_storage(cwd)
    assert path.is_dir()


def test_workspace_storage_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second call on an existing storage dir is a no-op."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cwd = tmp_path / "project"
    cwd.mkdir()
    first = workspace_storage(cwd)
    (first / "marker").write_text("keep me", encoding="utf-8")
    second = workspace_storage(cwd)
    assert second == first
    assert (second / "marker").read_text(encoding="utf-8") == "keep me"


def test_workspace_storage_distinct_for_distinct_cwds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    dir_a = tmp_path / "alpha"
    dir_a.mkdir()
    dir_b = tmp_path / "beta"
    dir_b.mkdir()
    assert workspace_storage(dir_a) != workspace_storage(dir_b)


def test_workspace_storage_skips_get_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Derived purely from ``workspace_id`` + ``Path.home``.

    The @lru_cache on ``get_settings`` and the TRANSPORT_MATTERS_STORAGE_DIR env
    var must not influence the returned path.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TRANSPORT_MATTERS_STORAGE_DIR", str(tmp_path / "unused"))
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert workspace_storage(cwd) == workspace_root(cwd)
    # Sanity: the env var we set is NOT the returned path.
    assert workspace_storage(cwd) != tmp_path / "unused"
