"""Tests for GET /v1/runs/run-current/exchanges/{id}/turn-content."""

from typing import TYPE_CHECKING

from transport_matters.ir import InternalResponse, TextBlock, UsageStats
from transport_matters.storage.base import ExchangeArtifacts

from .test_exchanges_support import make_index_entry, make_ir

if TYPE_CHECKING:
    from httpx import AsyncClient


async def _seed_complete(exchange_id: str = "ex-001") -> None:
    from transport_matters.storage import get_storage

    storage = await get_storage()
    entry = make_index_entry(exchange_id)
    artifacts = ExchangeArtifacts(
        request_raw=b"{}",
        request_ir=make_ir(),
        response_ir=InternalResponse(
            id=f"msg_{exchange_id}",
            model="anthropic/claude-sonnet-4-20250514",
            provider="anthropic",
            content=[TextBlock(text="world")],
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=1, output_tokens=1),
        ),
    )
    await storage.persist_exchange(entry, artifacts)


async def test_turn_content_returns_user_and_response_text(
    client: AsyncClient,
) -> None:
    await _seed_complete()

    response = await client.get("/v1/runs/run-current/exchanges/ex-001/turn-content")

    assert response.status_code == 200
    assert response.json() == {
        "user_text": "hi",
        "response_text": "world",
        "stop_reason": "end_turn",
    }


async def test_turn_content_returns_404_for_missing(client: AsyncClient) -> None:
    response = await client.get("/v1/runs/run-current/exchanges/missing/turn-content")

    assert response.status_code == 404


async def test_turn_content_null_response_when_in_flight(
    client: AsyncClient,
) -> None:
    from transport_matters.storage import get_storage

    storage = await get_storage()
    entry = make_index_entry("ex-pending")
    artifacts = ExchangeArtifacts(
        request_raw=b"{}",
        request_ir=make_ir(),
        response_ir=None,
    )
    await storage.persist_exchange(entry, artifacts)

    response = await client.get("/v1/runs/run-current/exchanges/ex-pending/turn-content")

    assert response.status_code == 200
    assert response.json() == {
        "user_text": "hi",
        "response_text": None,
        "stop_reason": None,
    }
