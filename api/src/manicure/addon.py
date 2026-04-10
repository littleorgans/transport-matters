"""mitmproxy addon for Manicure Phase 2.

Captures /v1/messages exchanges, stores them, and emits SSE events.
No pipeline, no breakpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any  # Any: mitmproxy loader type is untyped

import uvicorn

from manicure import broadcast

if TYPE_CHECKING:
    from mitmproxy import http
from manicure.adapters import get_adapter
from manicure.config import get_settings
from manicure.ir import InternalRequest, InternalResponse, TextBlock, ToolUseBlock
from manicure.main import create_app
from manicure.storage import IndexEntry, ReqStats, ResStats, init_storage
from manicure.storage.base import ExchangeArtifacts

logger = logging.getLogger(__name__)


def _build_req_stats(ir: InternalRequest) -> ReqStats:
    """Build request stats from an InternalRequest."""
    system_chars = sum(len(sp.text) for sp in ir.system)
    tools_chars = sum(
        len(t.name) + len(t.description) + len(json.dumps(t.input_schema))
        for t in ir.tools
    )
    messages_chars = 0
    for msg in ir.messages:
        for block in msg.content:
            messages_chars += len(block.model_dump_json())

    return ReqStats(
        system_parts=len(ir.system),
        system_chars=system_chars,
        tools_count=len(ir.tools),
        tools_chars=tools_chars,
        messages_count=len(ir.messages),
        messages_chars=messages_chars,
        total_chars=system_chars + tools_chars + messages_chars,
    )


def _build_res_stats(
    res_ir: InternalResponse | None,
    raw_res: bytes,
    content_type: str,
) -> ResStats:
    """Build response stats from an InternalResponse or raw SSE bytes."""
    if "application/json" in content_type and res_ir is not None:
        text_chars = 0
        tool_calls = 0
        for block in res_ir.content:
            if isinstance(block, TextBlock):
                text_chars += len(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_calls += 1

        return ResStats(
            stop_reason=res_ir.stop_reason,
            input_tokens=res_ir.usage.input_tokens,
            output_tokens=res_ir.usage.output_tokens,
            cache_read_input_tokens=res_ir.usage.cache_read_input_tokens,
            text_chars=text_chars,
            tool_calls=tool_calls,
        )

    # SSE stream: scan for message_start and message_delta events
    return _parse_sse_stats(raw_res)


def _parse_sse_stats(raw: bytes) -> ResStats:
    """Extract stats from SSE event stream (best-effort)."""
    stop_reason: str | None = None
    input_tokens = 0
    output_tokens = 0
    cache_read_input_tokens = 0
    text_chars = 0
    tool_calls = 0

    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            continue
        try:
            event: dict[str, Any] = json.loads(payload)  # Any: SSE JSON payload
        except (json.JSONDecodeError, ValueError):
            continue

        event_type = event.get("type", "")

        if event_type == "message_start":
            msg = event.get("message", {})
            usage = msg.get("usage", {})
            input_tokens += usage.get("input_tokens", 0)
            cache_read_input_tokens += usage.get("cache_read_input_tokens", 0)

        elif event_type == "message_delta":
            delta = event.get("delta", {})
            if delta.get("stop_reason"):
                stop_reason = delta["stop_reason"]
            usage = event.get("usage", {})
            output_tokens += usage.get("output_tokens", 0)

        elif event_type == "content_block_start":
            cb = event.get("content_block", {})
            if cb.get("type") == "tool_use":
                tool_calls += 1

        elif event_type == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                text_chars += len(delta.get("text", ""))

    return ResStats(
        stop_reason=stop_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        text_chars=text_chars,
        tool_calls=tool_calls,
    )


class ManicureAddon:
    def load(self, loader: Any) -> None:  # Any: mitmproxy loader
        settings = get_settings()
        storage = init_storage(root=settings.storage_dir)
        from manicure.storage.disk import DiskStorageBackend

        if isinstance(storage, DiskStorageBackend):
            logger.info("Storage root: %s", storage.root)

        app = create_app()
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=settings.web_port,
            log_config=None,
        )
        server = uvicorn.Server(config)
        asyncio.ensure_future(server.serve())
        logger.info("Web UI: http://127.0.0.1:%d", settings.web_port)

    async def request(self, flow: http.HTTPFlow) -> None:
        if not flow.request.path.startswith("/v1/messages"):
            return
        adapter = get_adapter(flow)
        if adapter is None:
            return

        try:
            req_text = flow.request.get_text()
            if req_text is None:
                return
            raw = req_text.encode()
            ir = adapter.inbound_request(raw)
        except Exception:
            logger.exception("Failed to parse request for flow %s", flow.id)
            return

        flow.metadata["manicure_adapter"] = adapter
        flow.metadata["manicure_ir"] = ir
        flow.metadata["manicure_raw_req"] = raw

    async def response(self, flow: http.HTTPFlow) -> None:
        adapter = flow.metadata.get("manicure_adapter")
        ir = flow.metadata.get("manicure_ir")
        raw_req = flow.metadata.get("manicure_raw_req")
        if adapter is None or ir is None or raw_req is None:
            return

        from manicure.storage import get_storage

        storage = get_storage()

        exchange_id = flow.id
        ts = datetime.now(UTC)

        res_text = flow.response.get_text() if flow.response else None
        raw_res = res_text.encode() if res_text else b""
        content_type = (
            flow.response.headers.get("content-type", "") if flow.response else ""
        )

        res_ir = None
        res_stats = None
        if flow.response and raw_res:
            try:
                res_ir = adapter.inbound_response(raw_res, content_type)
                res_stats = _build_res_stats(res_ir, raw_res, content_type)
            except Exception:
                logger.exception("Failed to parse response for flow %s", exchange_id)

        req_stats = _build_req_stats(ir)

        ts_slug = ts.strftime("%Y%m%dT%H%M%S")
        entry = IndexEntry(
            id=exchange_id,
            ts=ts,
            provider=ir.provider,
            model=ir.model,
            path=f"exchanges/{ts_slug}-{exchange_id[:8]}/",
            req=req_stats,
            res=res_stats,
        )

        artifacts = ExchangeArtifacts(
            request_raw=raw_req,
            request_ir=ir,
            response_raw=raw_res or None,
            response_ir=res_ir,
        )

        try:
            await storage.append_index(entry)
            await storage.write_exchange(exchange_id, artifacts)
        except Exception:
            logger.exception("Failed to write exchange %s", exchange_id)
            return

        broadcast.emit(
            {
                "type": "exchange",
                "id": exchange_id,
                "ts": ts.isoformat(),
                "provider": ir.provider,
                "model": ir.model,
                "req": req_stats.model_dump(mode="json"),
                "res": (res_stats.model_dump(mode="json") if res_stats else None),
            }
        )


addons = [ManicureAddon()]
