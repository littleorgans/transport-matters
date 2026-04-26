"""Tests for the exchange detail endpoint."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from manicure.codex.derivation import CodexReplayRequest, derive_codex_turn_replay
from manicure.codex.test_derivation_support import make_context, make_message
from manicure.ir import InternalResponse, Message, TextBlock, UsageStats
from manicure.storage.base import ExchangeArtifacts

from .test_exchanges_support import make_audit, make_index_entry, make_ir

if TYPE_CHECKING:
    from httpx import AsyncClient


class TestGetExchange:
    async def test_get_existing(self, client: AsyncClient) -> None:
        from manicure.storage import get_storage

        storage = await get_storage()
        entry = make_index_entry()
        ir = make_ir()
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        artifacts = ExchangeArtifacts(request_raw=raw, request_ir=ir)

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["request_ir"]["model"] == "anthropic/claude-sonnet-4-20250514"
        assert data["request_curated_ir"] is None
        assert data["response_ir"] is None
        assert data["events"] is None
        assert data["turn"] is None
        assert data["codex_derived_artifacts"] is None

    async def test_get_returns_404_when_index_row_is_missing(
        self, client: AsyncClient
    ) -> None:
        from manicure.storage import get_storage

        storage = await get_storage()
        artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
            request_ir=make_ir(),
        )
        await storage.write_exchange("ex-orphan", artifacts)

        response = await client.get("/api/exchanges/ex-orphan")
        assert response.status_code == 404

    async def test_get_existing_surfaces_curated_ir(self, client: AsyncClient) -> None:
        """When a curated IR was persisted, the route must surface it."""
        from manicure.storage import get_storage

        storage = await get_storage()
        entry = make_index_entry()
        ir = make_ir()
        curated_ir = ir.model_copy(
            update={
                "messages": [
                    Message(role="user", content=[TextBlock(text="edited")]),
                ],
            }
        )
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        artifacts = ExchangeArtifacts(
            request_raw=raw,
            request_ir=ir,
            request_curated_ir=curated_ir,
        )

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["request_ir"]["messages"][0]["content"][0]["text"] == "hi"
        assert data["request_curated_ir"] is not None
        assert (
            data["request_curated_ir"]["messages"][0]["content"][0]["text"] == "edited"
        )

    async def test_get_existing_surfaces_audit_and_transport(
        self, client: AsyncClient
    ) -> None:
        from manicure.storage import get_storage

        storage = await get_storage()
        entry = make_index_entry()
        ir = make_ir()
        artifacts = ExchangeArtifacts(
            request_raw=b'{"type":"response.create"}',
            request_ir=ir,
            request_audit=make_audit(),
            transport={
                "provider": "codex",
                "protocol": "websocket",
                "upgrade": {
                    "scheme": "wss",
                    "host": "chatgpt.com",
                    "path": "/backend-api/codex/responses?client=cli",
                    "request_headers": [
                        {"name": "x-codex-session", "value": "sess-123"},
                        {"name": "authorization", "value": "Bearer raw-secret"},
                    ],
                    "response_status_code": 101,
                    "response_headers": [
                        {"name": "set-cookie", "value": "session=secret; Path=/"},
                        {"name": "x-upstream", "value": "chatgpt"},
                    ],
                },
                "close": {
                    "close_code": 1000,
                    "close_reason": None,
                    "closed_by_client": False,
                    "initial_client_frame_captured": True,
                    "client_message_count": 1,
                    "server_message_count": 2,
                },
                "messages": [
                    {
                        "direction": "server",
                        "is_text": True,
                        "size_bytes": 32,
                        "dropped": False,
                        "event_type": "response.completed",
                        "payload_text": '{"type":"response.completed"}',
                        "payload_json": {"type": "response.completed"},
                        "payload_base64": None,
                    }
                ],
            },
        )

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["request_audit"] is not None
        assert data["request_audit"]["entries"][0]["target"] == "msg:0:blk:0"
        assert data["transport"] is not None
        assert data["transport"]["upgrade"]["host"] == "chatgpt.com"
        request_headers = {
            header["name"]: header["value"]
            for header in data["transport"]["upgrade"]["request_headers"]
        }
        response_headers = {
            header["name"]: header["value"]
            for header in data["transport"]["upgrade"]["response_headers"]
        }
        assert request_headers["authorization"] == "Bearer [redacted]"
        assert request_headers["x-codex-session"] == "[redacted]"
        assert response_headers["set-cookie"] == "[redacted]"
        assert data["transport"]["messages"][0]["event_type"] == "response.completed"
        assert data["transport_diagnostics"] == []
        assert data["events"] is None
        assert data["turn"] is None

    async def test_get_existing_surfaces_codex_events_and_turn_without_raw_payloads(
        self, client: AsyncClient
    ) -> None:
        from manicure.storage import get_storage

        storage = await get_storage()
        entry = make_index_entry().model_copy(
            update={
                "provider": "codex",
                "model": "codex/gpt-5-codex",
            }
        )
        ir = make_ir().model_copy(
            update={
                "provider": "codex",
                "model": "codex/gpt-5-codex",
            }
        )

        tool_arguments = '{"path":"secrets.txt","token":"raw-secret"}'
        assistant_text = "hidden assistant output"
        derived = derive_codex_turn_replay(
            CodexReplayRequest(
                context=make_context(
                    exchange_id="ex-001",
                    session_id="ws-api",
                    turn_id="turn-001",
                    turn_index=1,
                    model="codex/gpt-5-codex",
                ),
                transport_messages=[
                    make_message(
                        23,
                        10,
                        14,
                        3,
                        direction="client",
                        event_type="response.create",
                        payload_json={
                            "type": "response.create",
                            "model": "gpt-5-codex",
                        },
                    ),
                    make_message(
                        24,
                        10,
                        14,
                        4,
                        direction="server",
                        event_type="response.output_item.added",
                        payload_json={
                            "type": "response.output_item.added",
                            "item": {
                                "type": "function_call",
                                "id": "fc_01",
                                "call_id": "call_secret",
                                "name": "read_file",
                                "arguments": "",
                            },
                        },
                    ),
                    make_message(
                        25,
                        10,
                        14,
                        5,
                        direction="server",
                        event_type="response.function_call_arguments.done",
                        payload_json={
                            "type": "response.function_call_arguments.done",
                            "item_id": "fc_01",
                            "call_id": "call_secret",
                            "arguments": tool_arguments,
                        },
                    ),
                    make_message(
                        26,
                        10,
                        14,
                        6,
                        direction="server",
                        event_type="response.output_item.done",
                        payload_json={
                            "type": "response.output_item.done",
                            "item": {
                                "type": "function_call",
                                "id": "fc_01",
                                "call_id": "call_secret",
                                "name": "read_file",
                                "arguments": tool_arguments,
                            },
                        },
                    ),
                    make_message(
                        27,
                        10,
                        14,
                        7,
                        direction="server",
                        event_type="response.output_text.delta",
                        payload_json={
                            "type": "response.output_text.delta",
                            "item_id": "msg_01",
                            "delta": assistant_text,
                        },
                    ),
                    make_message(
                        28,
                        10,
                        14,
                        8,
                        direction="server",
                        event_type="response.output_item.done",
                        payload_json={
                            "type": "response.output_item.done",
                            "item": {
                                "id": "msg_01",
                                "type": "message",
                                "status": "completed",
                                "phase": "final_answer",
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": assistant_text,
                                    }
                                ],
                            },
                        },
                    ),
                    make_message(
                        29,
                        10,
                        14,
                        9,
                        direction="server",
                        event_type="response.completed",
                        payload_json={
                            "type": "response.completed",
                            "response": {
                                "id": "resp_01",
                                "status": "completed",
                            },
                        },
                    ),
                ],
            )
        )
        assert derived is not None

        artifacts = ExchangeArtifacts(
            request_raw=b'{"type":"response.create"}',
            request_ir=ir,
            events=derived.events,
            turn=derived.turn,
        )

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["transport"] is None
        assert data["transport_diagnostics"] == []
        assert [event["kind"] for event in data["events"]] == [
            "turn_started",
            "tool_call_completed",
            "assistant_item_completed",
            "response_completed",
            "turn_finalized",
        ]
        assert data["events"][1]["data"] == {
            "arguments_chars": len(tool_arguments),
            "call_id": "call_secret",
            "item_id": "fc_01",
            "item_type": "function_call",
            "tool_name": "read_file",
        }
        assert data["events"][2]["data"] == {
            "item_id": "msg_01",
            "item_type": "message",
            "phase": "final_answer",
            "role": "assistant",
            "text_chars": len(assistant_text),
        }
        assert data["turn"]["status"] == "completed"
        assert data["turn"]["turn_id"] == "turn-001"
        assert data["turn"]["terminal_cause"] == "response_completed"
        assert data["turn"]["derivation_version"] == 1
        assert data["codex_derived_artifacts"] == {
            "status": "supported",
            "diagnostics": [],
            "repair": None,
        }

        events_json = json.dumps(data["events"], sort_keys=True)
        assert tool_arguments not in events_json
        assert assistant_text not in events_json
        assert "raw-secret" not in events_json

    async def test_get_existing_surfaces_codex_transport_diagnostics(
        self, client: AsyncClient
    ) -> None:
        from manicure.storage import get_storage

        storage = await get_storage()
        entry = make_index_entry().model_copy(
            update={
                "provider": "codex",
                "model": "codex/transport-handshake",
            }
        )
        ir = make_ir().model_copy(
            update={
                "provider": "codex",
                "model": "codex/transport-handshake",
            }
        )
        artifacts = ExchangeArtifacts(
            request_raw=b"",
            request_ir=ir,
            response_raw=b"TLS error: invalid peer certificate: UnknownIssuer",
            transport={
                "provider": "codex",
                "protocol": "websocket",
                "upgrade": {
                    "scheme": "wss",
                    "host": "chatgpt.com",
                    "path": "/backend-api/codex/responses?client=cli",
                    "request_headers": [],
                    "response_status_code": 502,
                    "response_headers": [
                        {"name": "content-type", "value": "text/plain"}
                    ],
                },
                "close": None,
                "messages": [],
            },
        )

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["transport_diagnostics"][0]["code"] == "proxy_trust_failed"
        assert "response body redacted" in data["transport_diagnostics"][0]["detail"]
        assert "UnknownIssuer" not in data["transport_diagnostics"][0]["detail"]

    async def test_get_existing_redacts_codex_auth_rejection_body(
        self, client: AsyncClient
    ) -> None:
        from manicure.storage import get_storage

        storage = await get_storage()
        entry = make_index_entry().model_copy(
            update={
                "provider": "codex",
                "model": "codex/transport-handshake",
            }
        )
        ir = make_ir().model_copy(
            update={
                "provider": "codex",
                "model": "codex/transport-handshake",
            }
        )
        artifacts = ExchangeArtifacts(
            request_raw=b"",
            request_ir=ir,
            response_raw=b'{"detail":"Unauthorized websocket upgrade"}',
            transport={
                "provider": "codex",
                "protocol": "websocket",
                "upgrade": {
                    "scheme": "wss",
                    "host": "chatgpt.com",
                    "path": "/backend-api/codex/responses?client=cli",
                    "request_headers": [],
                    "response_status_code": 403,
                    "response_headers": [
                        {"name": "content-type", "value": "application/json"}
                    ],
                },
                "close": None,
                "messages": [],
            },
        )

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["transport_diagnostics"][0]["code"] == "chatgpt_auth_rejected"
        assert "response body redacted" in data["transport_diagnostics"][0]["detail"]
        assert (
            "status indicates an upstream auth challenge"
            in data["transport_diagnostics"][0]["detail"]
        )
        assert (
            "Unauthorized websocket upgrade"
            not in data["transport_diagnostics"][0]["detail"]
        )

    async def test_get_existing_redacts_generic_codex_handshake_failure_body(
        self, client: AsyncClient
    ) -> None:
        from manicure.storage import get_storage

        storage = await get_storage()
        entry = make_index_entry().model_copy(
            update={
                "provider": "codex",
                "model": "codex/transport-handshake",
            }
        )
        ir = make_ir().model_copy(
            update={
                "provider": "codex",
                "model": "codex/transport-handshake",
            }
        )
        artifacts = ExchangeArtifacts(
            request_raw=b"",
            request_ir=ir,
            response_raw=b"upstream timeout: raw-secret",
            transport={
                "provider": "codex",
                "protocol": "websocket",
                "upgrade": {
                    "scheme": "wss",
                    "host": "chatgpt.com",
                    "path": "/backend-api/codex/responses?client=cli",
                    "request_headers": [],
                    "response_status_code": 504,
                    "response_headers": [
                        {"name": "content-type", "value": "text/plain"}
                    ],
                },
                "close": None,
                "messages": [],
            },
        )

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["transport_diagnostics"][0]["code"] == "websocket_handshake_failed"
        assert (
            "response body redacted (28 bytes)"
            in data["transport_diagnostics"][0]["detail"]
        )
        assert "raw-secret" not in data["transport_diagnostics"][0]["detail"]

    async def test_get_existing_keeps_mixed_provider_rows_distinct(
        self, client: AsyncClient
    ) -> None:
        from manicure.storage import get_storage

        storage = await get_storage()
        anthropic_entry = make_index_entry("ex-anth", run_id="run-current")
        anthropic_ir = make_ir()
        anthropic_artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
            request_ir=anthropic_ir,
            response_ir=InternalResponse(
                id="msg_01",
                model="anthropic/claude-sonnet-4-20250514",
                provider="anthropic",
                stop_reason="end_turn",
                usage=UsageStats(input_tokens=11, output_tokens=7),
                content=[TextBlock(text="done")],
                provider_extras={},
            ),
        )
        codex_entry = make_index_entry("ex-codex", run_id="run-old").model_copy(
            update={
                "provider": "codex",
                "model": "codex/transport-handshake",
            }
        )
        codex_ir = make_ir().model_copy(
            update={
                "provider": "codex",
                "model": "codex/transport-handshake",
            }
        )
        codex_artifacts = ExchangeArtifacts(
            request_raw=b"",
            request_ir=codex_ir,
            response_raw=b"TLS error: invalid peer certificate: UnknownIssuer",
            transport={
                "provider": "codex",
                "protocol": "websocket",
                "upgrade": {
                    "scheme": "wss",
                    "host": "chatgpt.com",
                    "path": "/backend-api/codex/responses?client=cli",
                    "request_headers": [],
                    "response_status_code": 502,
                    "response_headers": [
                        {"name": "content-type", "value": "text/plain"}
                    ],
                },
                "close": None,
                "messages": [],
            },
        )

        await storage.append_index(anthropic_entry)
        await storage.write_exchange("ex-anth", anthropic_artifacts)
        await storage.append_index(codex_entry)
        await storage.write_exchange("ex-codex", codex_artifacts)

        anthropic_response = await client.get("/api/exchanges/ex-anth")
        assert anthropic_response.status_code == 200
        anthropic_data = anthropic_response.json()
        assert anthropic_data["entry"]["provider"] == "anthropic"
        assert anthropic_data["response_ir"]["provider"] == "anthropic"
        assert anthropic_data["response_ir"]["content"][0]["text"] == "done"
        assert anthropic_data["transport"] is None
        assert anthropic_data["transport_diagnostics"] == []

        codex_response = await client.get("/api/exchanges/ex-codex")
        assert codex_response.status_code == 200
        codex_data = codex_response.json()
        assert codex_data["entry"]["provider"] == "codex"
        assert codex_data["response_ir"] is None
        assert codex_data["transport"]["provider"] == "codex"
        assert codex_data["transport_diagnostics"][0]["code"] == "proxy_trust_failed"
        assert "UnknownIssuer" not in codex_data["transport_diagnostics"][0]["detail"]
