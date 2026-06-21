from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters.api.v1.session_test_support import session_client as _client
from transport_matters.config import get_settings
from transport_matters.main import create_app, lifespan
from transport_matters.session.pool import create_async_pool
from transport_matters.space.detection import DetectedSpace, DetectedWorktree, repo_instance_key
from transport_matters.space.store import SpaceStore
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from transport_matters.session.testing import TestDb

BACKEND_ORIGIN = "http://localhost:8788"


def _headers() -> dict[str, str]:
    return {"origin": BACKEND_ORIGIN, "host": "localhost:8788"}


def _worktree(
    path: Path,
    *,
    branch: str | None = None,
    head: str | None = None,
    is_primary: bool = False,
) -> DetectedWorktree:
    workspace = workspace_id(path)
    return DetectedWorktree(
        path=path.resolve(strict=False),
        workspace_slug=workspace.slug,
        workspace_hash=workspace.hash,
        branch_name=branch,
        head_oid=head,
        is_primary=is_primary,
    )


def _git_detection(root: Path, *worktrees: Path) -> DetectedSpace:
    common_dir = root / ".git"
    return DetectedSpace(
        name="repo",
        primary_path=root.resolve(strict=False),
        repo_instance_key=repo_instance_key(common_dir),
        git_common_dir=common_dir.resolve(strict=False),
        worktrees=(
            _worktree(root, branch="main", head="abc123", is_primary=True),
            *(_worktree(path, branch="feature", head="def456") for path in worktrees),
        ),
    )


async def test_resolve_path_returns_camel_case_summaries_and_lists(
    test_db: TestDb,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    repo.mkdir()
    linked.mkdir()
    monkeypatch.setattr(
        "transport_matters.space.store.detect_space", lambda cwd: _git_detection(repo)
    )

    async with _client(test_db) as client:
        legacy = await client.get("/api/spaces")
        assert legacy.status_code == 404

        resolved = await client.post(
            "/v1/spaces/resolve",
            json={"cwd": str(repo), "create": True},
            headers=_headers(),
        )
        assert resolved.status_code == 200
        payload = resolved.json()
        space_id = payload["space"]["spaceId"]
        worktree_id = payload["worktree"]["worktreeId"]
        assert payload["space"] == {
            "spaceId": space_id,
            "label": "repo",
            "kind": "repo",
            "archived": False,
            "createdAt": payload["space"]["createdAt"],
            "updatedAt": payload["space"]["updatedAt"],
            "worktrees": [payload["worktree"]],
        }
        assert payload["worktree"]["branch"] == "main"
        assert payload["worktree"]["headOid"] == "abc123"
        assert payload["worktree"]["isPrimary"] is True
        assert payload["worktree"]["workspaceSlug"] == workspace_id(repo).slug
        assert payload["canvases"] == []
        assert "workspaceId" not in payload["worktree"]
        assert "branch_name" not in payload["worktree"]
        assert "is_primary" not in payload["worktree"]

        listed = await client.get("/v1/spaces")
        assert listed.status_code == 200
        listed_item = listed.json()["items"][0]
        assert listed_item["spaceId"] == space_id
        assert [item["worktreeId"] for item in listed_item["worktrees"]] == [worktree_id]

        detail = await client.get(f"/v1/spaces/{space_id}")
        assert detail.status_code == 200
        assert [item["worktreeId"] for item in detail.json()["worktrees"]] == [worktree_id]

        canvas = await client.post(
            f"/v1/spaces/{space_id}/canvases",
            json={
                "label": "Main canvas",
                "defaultWorktreeId": worktree_id,
                "layout": {"panes": []},
            },
            headers=_headers(),
        )
        assert canvas.status_code == 201
        canvas_payload = canvas.json()["canvas"]
        assert canvas_payload["label"] == "Main canvas"
        assert canvas_payload["defaultWorktreeId"] == worktree_id

        canvases = await client.get(f"/v1/spaces/{space_id}/canvases")
        assert canvases.status_code == 200
        assert [item["canvasId"] for item in canvases.json()["items"]] == [
            canvas_payload["canvasId"]
        ]

        patched = await client.patch(
            f"/v1/canvases/{canvas_payload['canvasId']}",
            json={"label": "Renamed canvas"},
            headers=_headers(),
        )
        assert patched.status_code == 200
        assert patched.json()["canvas"]["label"] == "Renamed canvas"

        monkeypatch.setattr(
            "transport_matters.space.store.detect_space", lambda cwd: _git_detection(repo, linked)
        )
        refreshed = await client.get(f"/v1/spaces/{space_id}/worktrees", params={"refresh": "true"})
        assert refreshed.status_code == 200
        paths = {item["path"] for item in refreshed.json()["items"]}
        assert paths == {str(repo.resolve()), str(linked.resolve())}


async def test_resolve_plain_space_derives_plain_kind_and_create_false_is_lookup_only(
    test_db: TestDb,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr(
        "transport_matters.space.store.detect_space",
        lambda cwd: DetectedSpace(
            name="plain",
            primary_path=plain.resolve(),
            repo_instance_key=None,
            git_common_dir=None,
            worktrees=(_worktree(plain, is_primary=True),),
        ),
    )

    async with _client(test_db) as client:
        missing = await client.post(
            "/v1/spaces/resolve",
            json={"cwd": str(plain), "create": False},
            headers=_headers(),
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "space_not_found"

        created = await client.post(
            "/v1/spaces/resolve",
            json={"cwd": str(plain)},
            headers=_headers(),
        )
        assert created.status_code == 200
        assert created.json()["space"]["kind"] == "plain"
        space_id = created.json()["space"]["spaceId"]

        hidden = await client.get(f"/v1/spaces/{space_id}", params={"owner": "other"})
        assert hidden.status_code == 404
        assert hidden.json()["detail"]["code"] == "space_not_found"


async def test_lifespan_resolves_api_cwd_into_current_space(
    test_db: TestDb,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cwd = tmp_path / "api-cwd"
    cwd.mkdir()
    monkeypatch.setenv("TRANSPORT_MATTERS_DATABASE_URL", test_db.database_url)
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(cwd))
    monkeypatch.setattr(
        "transport_matters.main.resolve_database_url", lambda _settings: test_db.database_url
    )
    monkeypatch.setattr(
        "transport_matters.space.store.detect_space",
        lambda detected_cwd: DetectedSpace(
            name="api-cwd",
            primary_path=cwd.resolve(),
            repo_instance_key=None,
            git_common_dir=None,
            worktrees=(_worktree(cwd, is_primary=True),),
        ),
    )
    get_settings.cache_clear()
    app = create_app()

    try:
        async with lifespan(app):
            pass
        async with (
            create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
            pool.connection() as conn,
        ):
            spaces = await SpaceStore(conn, storage_dir=tmp_path / "storage").list_spaces()
    finally:
        get_settings.cache_clear()

    assert [item.space.name for item in spaces] == ["api-cwd"]
