"""CRUD endpoints for pipeline rules."""

from __future__ import annotations

from typing import Any  # Any: rule params vary by action type

from fastapi import APIRouter, Depends, Response

from manicure.exceptions import NotFoundError
from manicure.rules import Rule
from manicure.storage import StorageBackend, get_storage

router = APIRouter()


@router.get("")
async def list_rules(
    storage: StorageBackend = Depends(get_storage),
) -> list[Rule]:
    data = await storage.load_rules()
    return [Rule.model_validate(r) for r in data]


@router.post("", status_code=201)
async def create_rule(
    body: dict[str, Any],  # Any: rule body is partially opaque (params field)
    storage: StorageBackend = Depends(get_storage),
) -> Rule:
    # Strip server-generated fields so defaults apply
    body.pop("id", None)
    body.pop("created_at", None)
    body.pop("applied_count", None)
    rule = Rule.model_validate(body)

    data = await storage.load_rules()
    data.append(rule.model_dump(mode="json", by_alias=True))
    await storage.save_rules(data)
    return rule


@router.patch("/{rule_id}")
async def patch_rule(
    rule_id: str,
    body: dict[str, Any],  # Any: partial update body
    storage: StorageBackend = Depends(get_storage),
) -> Rule:
    data = await storage.load_rules()
    for i, raw in enumerate(data):
        rule = Rule.model_validate(raw)
        if rule.id == rule_id:
            merged = {**rule.model_dump(mode="json", by_alias=True)}
            for key in ("name", "enabled", "params"):
                if key in body:
                    merged[key] = body[key]
            updated = Rule.model_validate(merged)
            data[i] = updated.model_dump(mode="json", by_alias=True)
            await storage.save_rules(data)
            return updated

    raise NotFoundError(detail=f"Rule {rule_id} not found")


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    data = await storage.load_rules()
    original_len = len(data)
    data = [r for r in data if Rule.model_validate(r).id != rule_id]
    if len(data) == original_len:
        raise NotFoundError(detail=f"Rule {rule_id} not found")

    await storage.save_rules(data)
    return Response(status_code=204)
