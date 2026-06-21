from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from transport_matters.space.models import (
    Canvas,
    CanvasId,
    ResolvedWorktree,
    Space,
    SpaceId,
    Worktree,
    WorktreeId,
    shortest_unambiguous_prefix,
)

FIXED_UUID = UUID("12345678-1234-4234-9234-123456789abc")


class IdEnvelope(BaseModel):
    space_id: SpaceId
    worktree_id: WorktreeId
    canvas_id: CanvasId


def test_space_ids_are_uuid4_backed_and_dump_to_bare_strings() -> None:
    generated = SpaceId.new()

    assert generated.as_uuid().version == 4

    envelope = IdEnvelope(
        space_id=SpaceId.from_uuid(FIXED_UUID),
        worktree_id=WorktreeId.from_uuid(FIXED_UUID),
        canvas_id=CanvasId.from_uuid(FIXED_UUID),
    )

    assert envelope.space_id.as_uuid() == FIXED_UUID
    assert envelope.model_dump() == {
        "space_id": "12345678-1234-4234-9234-123456789abc",
        "worktree_id": "12345678-1234-4234-9234-123456789abc",
        "canvas_id": "12345678-1234-4234-9234-123456789abc",
    }
    assert envelope.model_dump_json() == (
        '{"space_id":"12345678-1234-4234-9234-123456789abc",'
        '"worktree_id":"12345678-1234-4234-9234-123456789abc",'
        '"canvas_id":"12345678-1234-4234-9234-123456789abc"}'
    )


def test_ids_validate_from_uuid_instances_and_uuid_strings() -> None:
    envelope = IdEnvelope(
        space_id=FIXED_UUID,
        worktree_id=str(FIXED_UUID),
        canvas_id=CanvasId.from_uuid(FIXED_UUID),
    )

    assert envelope.space_id == SpaceId.from_uuid(FIXED_UUID)
    assert envelope.worktree_id == WorktreeId.from_uuid(FIXED_UUID)
    assert envelope.canvas_id == CanvasId.from_uuid(FIXED_UUID)


def test_id_values_remain_type_separated() -> None:
    space_id = SpaceId.from_uuid(FIXED_UUID)
    worktree_id = WorktreeId.from_uuid(FIXED_UUID)

    assert space_id != worktree_id
    assert hash(space_id) != hash(worktree_id)


def test_id_validation_rejects_non_uuid_values() -> None:
    with pytest.raises(ValidationError):
        IdEnvelope(
            space_id=7,
            worktree_id=FIXED_UUID,
            canvas_id=FIXED_UUID,
        )


def test_short_prefix_helper_matches_littleorgans_floor() -> None:
    space_id = SpaceId.from_uuid(FIXED_UUID)

    assert shortest_unambiguous_prefix(str(space_id), lambda _: True) == "1234567"
    assert shortest_unambiguous_prefix(str(space_id), lambda candidate: len(candidate) == 9) == (
        "12345678-"
    )
    assert shortest_unambiguous_prefix("abc", lambda _: True) == "abc"
    assert space_id.short() == "1234567"
    assert space_id.short_with(lambda candidate: len(candidate) == 9) == "12345678-"


def test_space_worktree_canvas_models_are_frozen_pydantic_rows() -> None:
    space_id = SpaceId.from_uuid(FIXED_UUID)
    worktree_id = WorktreeId.from_uuid(UUID("aaaaaaaa-aaaa-4aaa-9aaa-aaaaaaaaaaaa"))
    canvas_id = CanvasId.from_uuid(UUID("bbbbbbbb-bbbb-4bbb-9bbb-bbbbbbbbbbbb"))

    space = Space(space_id=space_id, name="Transport Matters")
    worktree = Worktree(
        worktree_id=worktree_id,
        space_id=space_id,
        path="/repo/main",
        workspace_slug="transport-matters",
        workspace_hash="hash-main",
    )
    canvas = Canvas(
        canvas_id=canvas_id,
        space_id=space_id,
        name="Main canvas",
        default_worktree_id=worktree_id,
        layout={"panes": []},
    )

    assert space.model_dump()["space_id"] == str(space_id)
    assert worktree.model_dump()["worktree_id"] == str(worktree_id)
    assert canvas.model_dump()["default_worktree_id"] == str(worktree_id)


def test_resolved_worktree_freezes_run_handoff_contract() -> None:
    resolved = ResolvedWorktree(
        space_id=SpaceId.from_uuid(FIXED_UUID),
        worktree_id=WorktreeId.from_uuid(UUID("aaaaaaaa-aaaa-4aaa-9aaa-aaaaaaaaaaaa")),
        cwd="/repo/main",
        workspace_slug="transport-matters",
        workspace_hash="hash-main",
        missing=False,
        archived=False,
    )

    assert resolved.model_dump() == {
        "space_id": "12345678-1234-4234-9234-123456789abc",
        "worktree_id": "aaaaaaaa-aaaa-4aaa-9aaa-aaaaaaaaaaaa",
        "cwd": "/repo/main",
        "workspace_slug": "transport-matters",
        "workspace_hash": "hash-main",
        "missing": False,
        "archived": False,
    }
