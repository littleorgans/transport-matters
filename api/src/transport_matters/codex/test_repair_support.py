import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from transport_matters.codex.exchange_derivation import replay_codex_derived_artifacts
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from transport_matters.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from pathlib import Path

    from mitmproxy import http

    from transport_matters.codex.derivation import CodexDerivedTurnArtifacts
    from transport_matters.overrides import OverrideAudit
    from transport_matters.storage.base import TransportArtifacts


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


def _ts(second: int) -> datetime:
    return datetime(2026, 4, 19, 12, 0, second, tzinfo=UTC)


def _payload_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _message(
    *,
    direction: str,
    second: int | None,
    payload: dict[str, object],
    dropped: bool = False,
) -> dict[str, object]:
    payload_text = _payload_json(payload)
    return {
        "ts": None if second is None else _ts(second),
        "direction": direction,
        "is_text": True,
        "size_bytes": len(payload_text.encode()),
        "dropped": dropped,
        "event_type": payload.get("type"),
        "payload_text": payload_text,
        "payload_json": payload,
        "payload_base64": None,
    }


def _codex_transport(
    *messages: dict[str, object],
    close: dict[str, object] | None = None,
    request_headers: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "provider": "codex",
        "protocol": "websocket",
        "upgrade": {
            "scheme": "wss",
            "host": "chatgpt.com",
            "path": "/backend-api/codex/responses",
            "request_headers": request_headers or [],
            "response_status_code": 101,
            "response_headers": [],
        },
        "close": close,
        "messages": list(messages),
    }


def _close(
    *,
    second: int | None,
    close_code: int | None = 1000,
    close_reason: str | None = "done",
    client_message_count: int = 1,
    server_message_count: int = 0,
) -> dict[str, object]:
    return {
        "ts": None if second is None else _ts(second),
        "close_code": close_code,
        "close_reason": close_reason,
        "closed_by_client": False,
        "initial_client_frame_captured": True,
        "client_message_count": client_message_count,
        "server_message_count": server_message_count,
    }


def _codex_ir(session_id: str = "ws_123") -> InternalRequest:
    return InternalRequest(
        model="codex/gpt-5-codex",
        provider="codex",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(
            session_id=session_id,
            provider_metadata={"session_id": session_id},
        ),
    )


def _write_sidecar(path: Path, payload: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(payload)


def _live_codex_derivation(
    *,
    exchange_id: str,
    request_ir: InternalRequest,
    transport: TransportArtifacts,
    audit: OverrideAudit | None = None,
    mutated_manually: bool = False,
) -> CodexDerivedTurnArtifacts:
    derived = replay_codex_derived_artifacts(
        cast(
            "http.HTTPFlow",
            SimpleNamespace(
                metadata={},
                request=SimpleNamespace(headers={}),
            ),
        ),
        exchange_id=exchange_id,
        request_state=SimpleNamespace(
            request_ir=request_ir,
            audit=audit,
            mutated_manually=mutated_manually,
        ),
        transport=transport,
        turn_index=0,
    )
    assert derived is not None
    return derived
