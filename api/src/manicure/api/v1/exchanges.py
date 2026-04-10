"""Exchange list and detail endpoints."""

from typing import Any  # Any: IR model_dump produces dict[str, Any]

from fastapi import APIRouter, Depends, Query

from manicure.exceptions import NotFoundError
from manicure.storage import StorageBackend, get_storage
from manicure.storage.base import IndexEntry

router = APIRouter()


@router.get("")
async def list_exchanges(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    storage: StorageBackend = Depends(get_storage),
) -> list[IndexEntry]:
    return await storage.read_index(limit=limit, offset=offset)


@router.get("/{exchange_id}")
async def get_exchange(
    exchange_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> dict[str, Any]:  # Any: IR model_dump produces dict[str, Any]
    try:
        artifacts = await storage.read_exchange(exchange_id)
    except FileNotFoundError as exc:
        raise NotFoundError(detail=f"Exchange {exchange_id} not found") from exc

    # TODO: include raw bodies (base64-encoded) in a future phase
    index_entries = await storage.read_index(limit=1000, offset=0)
    entry = next((e for e in index_entries if e.id == exchange_id), None)

    return {
        "entry": entry.model_dump(mode="json") if entry else None,
        "request_ir": artifacts.request_ir.model_dump(mode="json"),
        "response_ir": (
            artifacts.response_ir.model_dump(mode="json")
            if artifacts.response_ir
            else None
        ),
    }
