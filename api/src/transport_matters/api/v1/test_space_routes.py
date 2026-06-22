from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters.api.v1.session_test_support import session_client as _client
from transport_matters.session.pool import create_async_pool
from transport_matters.space.detection import DetectedSpace, DetectedWorktree, repo_instance_key
from transport_matters.space.store import SpaceStore
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

    import pytest
    from fastapi.testclient import TestClient

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


async def test_list_spaces_rejects_non_dict_cursor(test_db: TestDb) -> None:
    async with _client(test_db) as client:
        response = await client.get("/v1/spaces", params={"cursor": "NDI="})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_cursor"


async def test_patch_canvas_rejects_cross_space_default_worktree(
    test_db: TestDb,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_a = tmp_path / "repo-a"
    linked_a = tmp_path / "linked-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    linked_a.mkdir()
    repo_b.mkdir()

    def detect_space_for_cwd(cwd: Path) -> DetectedSpace:
        resolved = cwd.resolve(strict=False)
        if resolved in {repo_a.resolve(), linked_a.resolve()}:
            return _git_detection(repo_a, linked_a)
        if resolved == repo_b.resolve():
            return _git_detection(repo_b)
        raise AssertionError(f"unexpected cwd: {cwd}")

    monkeypatch.setattr("transport_matters.space.store.detect_space", detect_space_for_cwd)

    async with _client(test_db) as client:
        space_a_response = await client.post(
            "/v1/spaces/resolve",
            json={"cwd": str(repo_a)},
            headers=_headers(),
        )
        assert space_a_response.status_code == 200
        space_a = space_a_response.json()["space"]
        space_a_id = space_a["spaceId"]
        primary_worktree_id = next(
            item["worktreeId"]
            for item in space_a["worktrees"]
            if item["path"] == str(repo_a.resolve())
        )
        linked_worktree_id = next(
            item["worktreeId"]
            for item in space_a["worktrees"]
            if item["path"] == str(linked_a.resolve())
        )

        space_b_response = await client.post(
            "/v1/spaces/resolve",
            json={"cwd": str(repo_b)},
            headers=_headers(),
        )
        assert space_b_response.status_code == 200
        foreign_worktree_id = space_b_response.json()["worktree"]["worktreeId"]

        canvas_response = await client.post(
            f"/v1/spaces/{space_a_id}/canvases",
            json={"label": "Main canvas", "defaultWorktreeId": primary_worktree_id},
            headers=_headers(),
        )
        assert canvas_response.status_code == 201
        canvas_id = canvas_response.json()["canvas"]["canvasId"]

        cross_space_create = await client.post(
            f"/v1/spaces/{space_a_id}/canvases",
            json={"label": "Bad canvas", "defaultWorktreeId": foreign_worktree_id},
            headers=_headers(),
        )
        assert cross_space_create.status_code == 400
        assert cross_space_create.json()["detail"]["code"] == "invalid_worktree_id"

        cross_space_patch = await client.patch(
            f"/v1/canvases/{canvas_id}",
            json={"defaultWorktreeId": foreign_worktree_id},
            headers=_headers(),
        )
        assert cross_space_patch.status_code == cross_space_create.status_code
        assert (
            cross_space_patch.json()["detail"]["code"]
            == cross_space_create.json()["detail"]["code"]
        )

        canvases_after_reject = await client.get(f"/v1/spaces/{space_a_id}/canvases")
        assert canvases_after_reject.status_code == 200
        assert canvases_after_reject.json()["items"][0]["defaultWorktreeId"] == primary_worktree_id

        same_space_patch = await client.patch(
            f"/v1/canvases/{canvas_id}",
            json={"defaultWorktreeId": linked_worktree_id},
            headers=_headers(),
        )
        assert same_space_patch.status_code == 200
        assert same_space_patch.json()["canvas"]["defaultWorktreeId"] == linked_worktree_id


async def test_lifespan_resolves_api_cwd_into_current_space(
    test_db: TestDb,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lifespan_client: Callable[[], AbstractContextManager[TestClient]],
) -> None:
    cwd = tmp_path / "api-cwd"
    cwd.mkdir()
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(cwd))
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

    with lifespan_client():
        pass
    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        spaces = await SpaceStore(conn, storage_dir=tmp_path / "storage").list_spaces()

    assert [item.space.name for item in spaces] == ["api-cwd"]
