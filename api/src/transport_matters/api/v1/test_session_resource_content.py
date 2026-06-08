from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from transport_matters.api.v1.exchanges import exchange_detail_route
from transport_matters.api.v1.session_test_support import session_client
from transport_matters.session import exchange_correlation
from transport_matters.session.artifacts import artifact_hash
from transport_matters.session.dao import AsyncSessionDao
from transport_matters.session.pool import create_async_pool
from transport_matters.session.resource_content import BINARY_CONTENT_LIMIT
from transport_matters.session.test_foundation import event, root_session

if TYPE_CHECKING:
    from transport_matters.session.models import EventRow
    from transport_matters.session.testing import TestDb


@dataclass(frozen=True)
class SeedArtifact:
    hash: str
    media_type: str
    data: bytes
    session_id: str
    seq: int


async def _seed_resource_session(
    test_db: TestDb,
    events: list[EventRow],
    artifacts: list[SeedArtifact] | None = None,
    *,
    other_session: bool = False,
) -> None:
    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        dao = AsyncSessionDao(conn)
        await dao.upsert_session(root_session("s1", native_session_id="native1"))
        if other_session:
            await dao.upsert_session(root_session("s2", native_session_id="native2"))
        for row in events:
            await dao.insert_event(row)
        for artifact in artifacts or []:
            await dao.upsert_artifact(artifact.data, media_type=artifact.media_type)
            await dao.link_artifact(artifact.session_id, artifact.seq, artifact.hash)


def _artifact(
    data: bytes, media_type: str, *, session_id: str = "s1", seq: int = 0
) -> SeedArtifact:
    return SeedArtifact(
        hash=artifact_hash(data),
        media_type=media_type,
        data=data,
        session_id=session_id,
        seq=seq,
    )


def _turn(seq: int = 0, *, session_id: str = "s1", raw: dict[str, Any] | None = None) -> EventRow:
    return event(seq, session_id=session_id).model_copy(
        update={
            "raw": raw or {"type": "turn", "message": {"role": "user", "content": "hello"}},
            "ir": {"parts": [{"type": "text", "text": "hello"}]},
            "search_text": "hello",
        }
    )


@pytest.mark.parametrize(
    ("media_type", "data", "expected_kind"),
    [
        ("text/plain", b"hello", "text"),
        ("application/json", b'{"ok":true}', "json"),
        ("image/png", b"\x89PNG\r\n\x1a\n", "image"),
        ("application/octet-stream", b"\x00\x01\x02", "binary"),
    ],
)
async def test_inline_resource_content_is_typed_by_media_type(
    test_db: TestDb, media_type: str, data: bytes, expected_kind: str
) -> None:
    artifact = _artifact(data, media_type)
    await _seed_resource_session(test_db, [_turn()], [artifact])

    async with session_client(test_db) as client:
        response = await client.get(f"/api/sessions/s1/resources/inline:{artifact.hash}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == expected_kind
    assert payload["id"] == f"inline:{artifact.hash}"
    assert payload["mediaType"] == media_type
    assert payload["contentLength"] == len(data)
    assert payload["contentProvenance"] == "inline-artifact"
    assert payload["provenance"]["artifactHash"] == artifact.hash
    assert "raw" not in payload
    if expected_kind == "text":
        assert payload["text"] == "hello"
        assert payload["encoding"] == "utf-8"
    elif expected_kind == "json":
        assert payload["value"] == {"ok": True}
        assert payload["truncated"] is False
    elif expected_kind == "image":
        assert payload["bytesBase64"] == base64.b64encode(data).decode("ascii")
        assert payload["url"] is None
    else:
        assert payload["sha256"] == hashlib.sha256(data).hexdigest()
        assert payload["downloadUrl"] is None
        assert payload["tooLarge"] is False


async def test_native_resource_content_returns_native_record_json(test_db: TestDb) -> None:
    raw = {"type": "turn", "message": {"role": "assistant", "content": "answer"}}
    await _seed_resource_session(test_db, [_turn(raw=raw)])

    async with session_client(test_db) as client:
        response = await client.get("/api/sessions/s1/resources/native:s1:0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "json"
    assert payload["id"] == "native:s1:0"
    assert payload["value"] == raw
    assert payload["mediaType"] == "application/json"
    assert payload["contentProvenance"] == "native-record"
    assert payload["provenance"]["sessionId"] == "s1"
    assert payload["provenance"]["seq"] == 0


async def test_wire_resource_content_redirects_without_payload_duplication(test_db: TestDb) -> None:
    row = _turn().model_copy(update={"ir": {"transport_matters": {"exchange_id": "exchange-1"}}})
    await _seed_resource_session(test_db, [row])

    async with session_client(test_db) as client:
        response = await client.get("/api/sessions/s1/resources/wire:exchange-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "exchange-redirect"
    assert payload["id"] == "wire:exchange-1"
    assert payload["exchangeId"] == "exchange-1"
    assert payload["route"] == exchange_detail_route("exchange-1")
    assert payload["initialView"] == "request"
    assert payload["contentProvenance"] == "structured-wire"
    assert "requestIr" not in payload
    assert "responseIr" not in payload
    assert "transport" not in payload


async def test_wire_resource_content_returns_uncorrelated_when_exchange_is_absent(
    test_db: TestDb,
) -> None:
    await _seed_resource_session(test_db, [_turn()])

    async with session_client(test_db) as client:
        response = await client.get("/api/sessions/s1/resources/wire:missing-exchange")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "missing"
    assert payload["reason"] == "uncorrelated"
    assert payload["retryable"] is False


async def test_wire_resource_content_uses_shared_exchange_correlation_params(
    test_db: TestDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    original = exchange_correlation.exchange_id_containment_params

    def spy(exchange_id: str) -> dict[str, Any]:
        calls.append(exchange_id)
        return original(exchange_id)

    monkeypatch.setattr(exchange_correlation, "exchange_id_containment_params", spy)
    row = _turn().model_copy(update={"ir": {"transport_matters": {"exchange_id": "exchange-1"}}})
    await _seed_resource_session(test_db, [row])

    async with session_client(test_db) as client:
        response = await client.get("/api/sessions/s1/resources/wire:exchange-1")

    assert response.status_code == 200
    assert calls == ["exchange-1"]


async def test_resource_content_rejects_ids_outside_session(test_db: TestDb) -> None:
    await _seed_resource_session(test_db, [_turn(), _turn(session_id="s2")], other_session=True)

    async with session_client(test_db) as client:
        response = await client.get("/api/sessions/s1/resources/native:s2:0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "missing"
    assert payload["reason"] == "not-found"
    assert payload["retryable"] is False


async def test_resource_content_returns_typed_missing_for_not_found_and_unsupported(
    test_db: TestDb,
) -> None:
    await _seed_resource_session(test_db, [_turn()])

    async with session_client(test_db) as client:
        missing = await client.get("/api/sessions/s1/resources/inline:missing")
        unsupported = await client.get("/api/sessions/s1/resources/tool-output:s1:0:0")

    assert missing.status_code == 200
    assert missing.json()["kind"] == "missing"
    assert missing.json()["reason"] == "not-found"
    assert unsupported.status_code == 200
    assert unsupported.json()["kind"] == "missing"
    assert unsupported.json()["reason"] == "unsupported"
    assert unsupported.json()["retryable"] is False


async def test_text_resource_content_supports_ranges(test_db: TestDb) -> None:
    data = b"abcdefghijklmnopqrstuvwxyz"
    artifact = _artifact(data, "text/plain")
    await _seed_resource_session(test_db, [_turn()], [artifact])

    async with session_client(test_db) as client:
        response = await client.get(
            f"/api/sessions/s1/resources/inline:{artifact.hash}",
            params={"range_start": 2, "range_end": 5},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "text"
    assert payload["text"] == "cde"
    assert payload["range"] == {"start": 2, "end": 5, "total": len(data)}
    assert payload["truncated"] is True


async def test_binary_resource_content_returns_typed_too_large(test_db: TestDb) -> None:
    data = b"x" * (BINARY_CONTENT_LIMIT + 1)
    artifact = _artifact(data, "application/octet-stream")
    await _seed_resource_session(test_db, [_turn()], [artifact])

    async with session_client(test_db) as client:
        response = await client.get(f"/api/sessions/s1/resources/inline:{artifact.hash}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "missing"
    assert payload["reason"] == "too-large"
    assert payload["mediaType"] == "application/octet-stream"
    assert payload["contentLength"] == len(data)
    assert payload["contentProvenance"] == "inline-artifact"
    assert payload["retryable"] is False


async def test_resource_content_withholds_raw_only_debug_resources_by_default(
    test_db: TestDb,
) -> None:
    await _seed_resource_session(test_db, [_turn()])

    async with session_client(test_db) as client:
        response = await client.get("/api/sessions/s1/resources/raw-provider:exchange-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "missing"
    assert payload["reason"] == "debug-unavailable"
    assert payload["retryable"] is False
