"""Exchange list and detail endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from manicure.exceptions import NotFoundError
from manicure.ir import InternalRequest, InternalResponse
from manicure.storage import StorageBackend, get_storage
from manicure.storage.base import IndexEntry

logger = logging.getLogger(__name__)

router = APIRouter()


class ExchangeDetailResponse(BaseModel):
    entry: IndexEntry | None
    request_ir: InternalRequest
    request_curated_ir: InternalRequest | None
    response_ir: InternalResponse | None


@router.get("")
async def list_exchanges(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    storage: StorageBackend = Depends(get_storage),
) -> list[IndexEntry]:
    try:
        return await storage.read_index(limit=limit, offset=offset)
    except Exception:
        logger.exception("Failed to read exchange index")
        return JSONResponse(  # type: ignore[return-value]
            status_code=500,
            content={"detail": "Failed to read exchange index"},
        )


@router.get("/{exchange_id}")
async def get_exchange(
    exchange_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> ExchangeDetailResponse:
    try:
        artifacts = await storage.read_exchange(exchange_id)
    except FileNotFoundError as exc:
        raise NotFoundError(detail=f"Exchange {exchange_id} not found") from exc

    entry = await storage.read_index_entry(exchange_id)

    return ExchangeDetailResponse(
        entry=entry,
        request_ir=artifacts.request_ir,
        request_curated_ir=artifacts.request_curated_ir,
        response_ir=artifacts.response_ir,
    )
