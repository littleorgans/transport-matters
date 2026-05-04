from __future__ import annotations

import pytest

from transport_matters.ir import InternalResponse, Message, TextBlock, UsageStats
from transport_matters.storage import test_disk as disk_tests
from transport_matters.storage.base import ExchangeArtifacts
from transport_matters.storage.disk import DiskStorageBackend


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


class TestWriteAndReadExchange:
    async def test_round_trip(self, storage: DiskStorageBackend) -> None:
        ir = disk_tests._make_ir()
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        artifacts = ExchangeArtifacts(request_raw=raw, request_ir=ir)

        await storage.write_exchange("abcdef01-1234", artifacts)
        loaded = await storage.read_exchange("abcdef01-1234")

        assert loaded.request_raw == raw
        assert loaded.request_ir == ir
        assert loaded.request_curated_raw is None
        assert loaded.request_curated_ir is None
        assert loaded.request_audit is None
        assert loaded.response_raw is None
        assert loaded.transport is None

    async def test_with_response(self, storage: DiskStorageBackend) -> None:
        ir = disk_tests._make_ir()
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        resp_raw = b'{"id":"msg_01","model":"claude-sonnet-4-20250514","content":[]}'
        resp_ir = InternalResponse(
            id="msg_01",
            model="anthropic/claude-sonnet-4-20250514",
            provider="anthropic",
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=10, output_tokens=20),
            content=[],
        )

        artifacts = ExchangeArtifacts(
            request_raw=raw,
            request_ir=ir,
            response_raw=resp_raw,
            response_ir=resp_ir,
        )
        await storage.write_exchange("bbccdd02-5678", artifacts)
        loaded = await storage.read_exchange("bbccdd02-5678")

        assert loaded.response_raw == resp_raw
        assert loaded.response_ir is not None
        assert loaded.response_ir.id == "msg_01"

    async def test_with_curated_request_audit_and_transport(
        self, storage: DiskStorageBackend
    ) -> None:
        ir = disk_tests._make_ir()
        curated_raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":256}'
        artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
            request_ir=ir,
            request_curated_raw=curated_raw,
            request_curated_ir=ir.model_copy(
                update={
                    "messages": [
                        Message(role="user", content=[TextBlock(text="patched")]),
                    ]
                }
            ),
            request_audit=disk_tests._make_audit(),
            transport={
                "provider": "codex",
                "protocol": "websocket",
                "upgrade": {
                    "scheme": "wss",
                    "host": "chatgpt.com",
                    "path": "/backend-api/codex/responses",
                    "request_headers": [
                        {"name": "authorization", "value": "Bearer super-secret"},
                        {"name": "x-test", "value": "1"},
                    ],
                    "response_status_code": 101,
                    "response_headers": [
                        {"name": "set-cookie", "value": "session=secret; Path=/"},
                        {"name": "x-upstream", "value": "chatgpt"},
                    ],
                },
                "close": {
                    "close_code": 1000,
                    "close_reason": "done",
                    "closed_by_client": False,
                    "initial_client_frame_captured": True,
                    "client_message_count": 1,
                    "server_message_count": 2,
                },
                "messages": [
                    {
                        "direction": "client",
                        "is_text": True,
                        "size_bytes": 24,
                        "dropped": False,
                        "event_type": "response.create",
                        "payload_text": '{"type":"response.create"}',
                        "payload_json": {"type": "response.create"},
                        "payload_base64": None,
                    }
                ],
            },
        )

        await storage.write_exchange("codex0001-5678", artifacts)
        loaded = await storage.read_exchange("codex0001-5678")

        assert loaded.request_curated_raw == curated_raw
        assert loaded.request_curated_ir is not None
        block = loaded.request_curated_ir.messages[0].content[0]
        assert isinstance(block, TextBlock)
        assert block.text == "patched"
        assert loaded.request_audit is not None
        assert loaded.request_audit.entries[0].target == "system:0"
        assert loaded.transport is not None
        assert loaded.transport.provider == "codex"
        assert loaded.transport.close is not None
        assert loaded.transport.close.close_code == 1000
        request_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.request_headers
        }
        response_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.response_headers
        }
        assert request_headers["authorization"] == "Bearer [redacted]"
        assert request_headers["x-test"] == "1"
        assert response_headers["set-cookie"] == "[redacted]"
        assert response_headers["x-upstream"] == "chatgpt"
        assert loaded.transport.messages[0].event_type == "response.create"

    async def test_rewrite_existing_exchange_dir(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "rewrite01-1234"
        original_ir = disk_tests._make_ir()
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(
                request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
                request_ir=original_ir,
            ),
        )
        original_dir = storage._find_exchange_dir(exchange_id)

        final_response = InternalResponse(
            id="msg_final",
            model="anthropic/claude-sonnet-4-20250514",
            provider="anthropic",
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=10, output_tokens=20),
            content=[TextBlock(text="done")],
        )
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(
                request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
                request_ir=original_ir,
                request_curated_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":256}',
                request_curated_ir=original_ir.model_copy(
                    update={
                        "messages": [
                            Message(role="user", content=[TextBlock(text="patched")])
                        ]
                    }
                ),
                response_raw=b'{"id":"msg_final"}',
                response_ir=final_response,
            ),
        )

        dirs = [path for path in storage.root.iterdir() if path.is_dir()]
        assert dirs == [original_dir]
        loaded = await storage.read_exchange(exchange_id)
        assert loaded.request_curated_raw is not None
        assert loaded.response_ir is not None
        assert loaded.response_ir.id == "msg_final"

    async def test_read_exchange_redacts_and_rewrites_legacy_transport_headers(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "legacy000-5678"
        exchange_dir = storage.root / f"20250601T120000Z-{exchange_id[:8]}"
        exchange_dir.mkdir()
        (exchange_dir / "request.raw").write_bytes(
            b'{"type":"response.create","model":"gpt-5-codex"}'
        )
        (exchange_dir / "request.ir.json").write_text(
            disk_tests._make_ir().model_dump_json()
        )
        (exchange_dir / "transport.json").write_text(
            """
{
  "provider": "codex",
  "protocol": "websocket",
  "upgrade": {
    "scheme": "wss",
    "host": "chatgpt.com",
    "path": "/backend-api/codex/responses",
    "request_headers": [
      {"name": "authorization", "value": "Bearer legacy-secret"},
      {"name": "origin", "value": "https://chatgpt.com"}
    ],
    "response_status_code": 403,
    "response_headers": [
      {"name": "set-cookie", "value": "session=legacy; Path=/"},
      {"name": "content-type", "value": "application/json"}
    ]
  },
  "close": null,
  "messages": []
}
""".strip()
        )

        loaded = await storage.read_exchange(exchange_id)

        assert loaded.transport is not None
        request_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.request_headers
        }
        response_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.response_headers
        }
        assert request_headers["authorization"] == "Bearer [redacted]"
        assert request_headers["origin"] == "https://chatgpt.com"
        assert response_headers["set-cookie"] == "[redacted]"
        assert response_headers["content-type"] == "application/json"

        persisted = (exchange_dir / "transport.json").read_text()
        assert "legacy-secret" not in persisted
        assert "session=legacy" not in persisted
        assert "Bearer [redacted]" in persisted

    async def test_not_found(self, storage: DiskStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.read_exchange("nonexistent-id")
