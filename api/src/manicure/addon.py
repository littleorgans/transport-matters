"""mitmproxy addon for Manicure.

Captures /v1/messages exchanges, applies pipeline rules, stores
artifacts, and emits SSE events.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any  # Any: mitmproxy loader type is untyped

import httpx
import uvicorn

from manicure import breakpoint as bp
from manicure import broadcast

if TYPE_CHECKING:
    from mitmproxy import http
from manicure.adapters import get_adapter
from manicure.config import get_settings
from manicure.counting import (
    TokenCounter,
    TokenCountingClient,
    _relevant_auth_headers,
    count_before_after,
    set_counter,
    set_recent_auth,
)
from manicure.ir import InternalRequest, InternalResponse, TextBlock, ToolUseBlock
from manicure.main import create_app
from manicure.overrides import (
    OverrideAudit,
    apply_overrides,
    count_chars_parts,
    get_store,
)
from manicure.storage import IndexEntry, PipelineStats, ReqStats, ResStats, init_storage
from manicure.storage.base import ExchangeArtifacts, StorageBackend

logger = logging.getLogger(__name__)


# ── Stats builders ──────────────────────────────────────────────────


def _build_req_stats(ir: InternalRequest) -> ReqStats:
    """Build request stats from an InternalRequest."""
    system_chars, tools_chars, messages_chars = count_chars_parts(ir)
    return ReqStats(
        system_parts=len(ir.system),
        system_chars=system_chars,
        tools_count=len(ir.tools),
        tools_chars=tools_chars,
        messages_count=sum(len(m.content) for m in ir.messages),
        messages_chars=messages_chars,
        total_chars=system_chars + tools_chars + messages_chars,
    )


def _build_res_stats(res_ir: InternalResponse) -> ResStats:
    """Derive the index row's response stats from a parsed IR.

    The adapter is authoritative for both JSON and SSE; the addon used to
    re-parse SSE here and drop fields in the process. Keeping one source
    of truth eliminates drift between the two code paths.
    """
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
        cache_creation_input_tokens=res_ir.usage.cache_creation_input_tokens,
        cache_read_input_tokens=res_ir.usage.cache_read_input_tokens,
        text_chars=text_chars,
        tool_calls=tool_calls,
    )


# ── Request phases ──────────────────────────────────────────────────


async def _parse_request_ir(
    flow: http.HTTPFlow,
    adapter: Any,  # Any: adapter protocol has no shared base
) -> tuple[bytes, InternalRequest] | None:
    """Decode raw request bytes and parse to IR. Returns None on failure."""
    try:
        req_text = flow.request.get_text()
        if req_text is None:
            return None
        raw = req_text.encode()
        ir = adapter.inbound_request(raw)
        return raw, ir
    except Exception:
        logger.exception("Failed to parse request for flow %s", flow.id)
        return None


async def _run_pipeline(
    ir: InternalRequest,
    flow_id: str,
) -> tuple[InternalRequest, OverrideAudit | None]:
    """Apply overrides from the store to the IR. Never raises."""
    store = get_store()
    if not store.enabled:
        return ir, None

    try:
        curated_ir, audit = apply_overrides(store.get_all(), ir)
    except Exception:
        logger.exception(
            "Override pipeline failed for flow %s, forwarding unmodified", flow_id
        )
        return ir, None

    return curated_ir, audit


def _resolve_paused_flow(pf: bp.PausedFlow) -> tuple[InternalRequest, bool]:
    """Decide the IR to forward and whether the user meaningfully edited it.

    A release via the Forward button populates ``pf.mutated_ir``, but that
    alone does not imply the user changed anything: the editor may have been
    opened and submitted unchanged. Declare manual mutation only when the
    submitted IR structurally diverges from the pipeline's ``curated_ir``.
    """
    if pf.mutated_ir is None:
        return pf.curated_ir, False
    return pf.mutated_ir, pf.mutated_ir != pf.curated_ir


async def _fire_pause_count(
    flow_id: str,
    counter: TokenCountingClient,
    payload: bytes,
    auth: dict[str, str],
) -> None:
    """Count tokens for a paused flow and announce the result on the bus.

    Runs fire-and-forget so the initial ``paused`` event reaches the UI
    immediately; a follow-up ``paused_tokens`` event carries the real
    count once the Anthropic round-trip completes. On failure (network,
    rate limit, malformed response, or race with a user release) no
    event is emitted and the UI keeps its em dash.
    """
    try:
        tokens = await counter.count(payload, auth)
    except Exception:
        logger.exception("count_tokens failed at breakpoint %s", flow_id)
        return
    if tokens is None:
        return
    if not await bp.set_tokens_before(flow_id, tokens):
        return
    broadcast.emit(
        {
            "type": "paused_tokens",
            "flow_id": flow_id,
            "tokens_before": tokens,
        }
    )


async def _handle_breakpoint(
    flow: http.HTTPFlow,
    adapter: Any,  # Any: adapter protocol has no shared base
    original_ir: InternalRequest,
    curated_ir: InternalRequest,
    audit: OverrideAudit | None,
    counter: TokenCountingClient | None,
) -> None:
    """Pause at breakpoint, await user action, rewrite request in place.

    Concurrent requests queue on ``bp.pause_serializer()`` so only one flow
    is presented to the user at a time. Other flows block here in FIFO order
    until the active flow is released.
    """
    from mitmproxy.http import Response as MitmResponse

    logger.info("BREAKPOINT %s waiting for serializer", flow.id)
    async with bp.pause_serializer():
        logger.info("BREAKPOINT %s acquired serializer, pausing", flow.id)
        auth = _relevant_auth_headers(flow.request.headers)
        paused_at_ms = int(time.time() * 1000)
        event = await bp.pause(flow, original_ir, curated_ir, audit, auth_headers=auth)
        broadcast.emit(
            {
                "type": "paused",
                "flow_id": flow.id,
                "ir": curated_ir.model_dump(mode="json"),
                "original_tools": [
                    t.model_dump(mode="json") for t in original_ir.tools
                ],
                "original_system": [
                    sp.model_dump(mode="json") for sp in original_ir.system
                ],
                "original_messages": [
                    m.model_dump(mode="json") for m in original_ir.messages
                ],
                "original_sampling": original_ir.sampling.model_dump(mode="json"),
                "original_provider_extras": dict(original_ir.provider_extras),
                "audit": audit.model_dump(mode="json") if audit else None,
                "paused_at_ms": paused_at_ms,
                # Filled in by _fire_pause_count via a follow-up paused_tokens
                # event; starting null keeps the initial UI render fast.
                "tokens_before": None,
            }
        )
        if counter is not None:
            asyncio.create_task(
                _fire_pause_count(
                    flow.id,
                    counter,
                    adapter.outbound_request(curated_ir),
                    auth,
                )
            )
        settings = get_settings()
        try:
            await asyncio.wait_for(event.wait(), timeout=settings.breakpoint_timeout_s)
        except TimeoutError:
            logger.warning(
                "Breakpoint timeout (%.0fs) for flow %s, auto-releasing",
                settings.breakpoint_timeout_s,
                flow.id,
            )

        pf = await bp.pop_paused(flow.id)
    if pf is None:
        return

    if pf.dropped:
        flow.response = MitmResponse.make(
            400,
            b'{"error": "dropped by user"}',
            {"content-type": "application/json"},
        )
        return

    final_ir, mutated_manually = _resolve_paused_flow(pf)
    flow.request.set_text(adapter.outbound_request(final_ir).decode())
    flow.metadata["manicure_mutated_manually"] = mutated_manually
    # Persist the IR that was actually sent to the provider so response()
    # writes it to request.curated.ir.json.
    flow.metadata["manicure_curated_ir"] = final_ir


# ── Response phases ─────────────────────────────────────────────────


def _parse_response_ir(
    adapter: Any,  # Any: adapter protocol has no shared base
    raw_res: bytes,
    content_type: str,
    exchange_id: str,
) -> tuple[InternalResponse | None, ResStats | None]:
    """Parse raw response bytes to IR and stats. Returns (None, None) on failure."""
    if not raw_res:
        return None, None
    try:
        res_ir = adapter.inbound_response(raw_res, content_type)
        res_stats = _build_res_stats(res_ir)
        return res_ir, res_stats
    except Exception:
        logger.exception("Failed to parse response for flow %s", exchange_id)
        return None, None


def _build_pipeline_stats(audit: OverrideAudit | None) -> PipelineStats | None:
    """Convert an OverrideAudit to the storable PipelineStats.

    Token counts start unset; a subsequent async stamp via count_tokens
    fills them in. Rows whose count call fails stay None and the UI
    renders an em dash rather than a fake chars/4 number.
    """
    if audit is None:
        return None
    return PipelineStats(
        overrides_applied=list(audit.entries),
        chars_before=audit.chars_before,
        chars_after=audit.chars_after,
    )


async def _stamp_pipeline_tokens(
    stats: PipelineStats,
    original_ir: InternalRequest,
    curated_ir: InternalRequest,
    adapter: Any,  # Any: adapter protocol has no shared base
    counter: TokenCountingClient,
    auth_headers: dict[str, str],
) -> PipelineStats:
    """Attach before/after token counts from /v1/messages/count_tokens.

    Delegates the byte-equality collapse and concurrent-count logic to
    ``count_before_after`` — the lazy-recount endpoint uses the same
    helper so the two paths can't drift.

    A None return on either side is treated as a partial failure: the
    stats object is returned unchanged so both token fields stay at
    None. Persisting a partial stamp like (42, None) would let the
    lazy-recount endpoint's "already stamped" short-circuit freeze the
    null side forever; leaving the row at (None, None) keeps it
    eligible for a future retry.
    """
    tokens_before, tokens_after = await count_before_after(
        counter,
        auth_headers,
        adapter.outbound_request(original_ir),
        adapter.outbound_request(curated_ir),
    )
    if tokens_before is None or tokens_after is None:
        return stats
    return stats.model_copy(
        update={"tokens_before": tokens_before, "tokens_after": tokens_after}
    )


async def _persist_exchange(
    storage: StorageBackend,
    entry: IndexEntry,
    artifacts: ExchangeArtifacts,
    exchange_id: str,
) -> bool:
    """Write index entry and artifacts. Returns False on failure."""
    try:
        await storage.append_index(entry)
        await storage.write_exchange(exchange_id, artifacts)
        return True
    except Exception:
        logger.exception("Failed to write exchange %s", exchange_id)
        return False


def _emit_exchange(
    ir: InternalRequest,
    req_stats: ReqStats,
    res_stats: ResStats | None,
    exchange_id: str,
    ts: datetime,
    mutated_manually: bool = False,
    pipeline_stats: PipelineStats | None = None,
    flow_id: str | None = None,
) -> None:
    """Broadcast the exchange event to SSE subscribers."""
    payload: dict[str, object] = {
        "type": "exchange",
        "id": exchange_id,
        "ts": ts.isoformat(),
        "provider": ir.provider,
        "model": ir.model,
        "req": req_stats.model_dump(mode="json"),
        "res": res_stats.model_dump(mode="json") if res_stats else None,
        "mutated_manually": mutated_manually,
        "pipeline": pipeline_stats.model_dump(mode="json") if pipeline_stats else None,
    }
    if flow_id is not None:
        payload["flow_id"] = flow_id
    broadcast.emit(payload)


# ── Addon ───────────────────────────────────────────────────────────


class ManicureAddon:
    def __init__(self) -> None:
        # Initialized in load() and closed in done(). Typed Optional so
        # response() can no-op gracefully if load() has not run yet (e.g.
        # tests that exercise phase helpers directly).
        self._http_client: httpx.AsyncClient | None = None
        self._token_counter: TokenCounter | None = None

    def load(self, loader: Any) -> None:  # Any: mitmproxy loader
        settings = get_settings()
        storage = init_storage(root=settings.storage_dir)
        from manicure.storage.disk import DiskStorageBackend

        if isinstance(storage, DiskStorageBackend):
            logger.info("Storage root: %s", storage.root)

        # trust_env=False so HTTPS_PROXY env vars do not loop the counter's
        # request back through Manicure's own proxy. We always want to hit
        # api.anthropic.com directly.
        self._http_client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0),
            trust_env=False,
        )
        self._token_counter = TokenCounter(self._http_client)
        # Publish the counter so FastAPI routes (re-audit) can recount
        # without reaching back through the live mitmproxy flow.
        set_counter(self._token_counter)

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
        try:
            adapter = get_adapter(flow)
        except Exception:
            logger.debug("No adapter matches flow %s, passing through", flow.id)
            return

        # Snapshot auth so lazy recount routes (e.g. historical pipeline
        # tokens) can replay credentials against count_tokens without a
        # live flow in hand. Refreshed on every inbound request, so a
        # rotated key propagates immediately.
        set_recent_auth(_relevant_auth_headers(flow.request.headers))

        result = await _parse_request_ir(flow, adapter)
        if result is None:
            return
        raw, ir = result

        logger.info(
            "REQ %s model=%s system=%d tools=%d msgs=%d",
            flow.id,
            ir.model,
            len(ir.system),
            len(ir.tools),
            len(ir.messages),
        )

        curated_ir, audit = await _run_pipeline(ir, flow.id)

        flow.metadata["manicure_adapter"] = adapter
        flow.metadata["manicure_ir"] = ir
        flow.metadata["manicure_raw_req"] = raw
        flow.metadata["manicure_curated_ir"] = curated_ir
        flow.metadata["manicure_audit"] = audit

        settings = get_settings()
        skip = any(s in ir.model for s in settings.breakpoint_skip_models)
        if skip:
            logger.info(
                "Breakpoint skip: %s matches breakpoint_skip_models filter",
                flow.id,
            )
        if not skip and bp.is_armed():
            logger.info("BREAKPOINT %s armed, pausing", flow.id)
            await _handle_breakpoint(
                flow, adapter, ir, curated_ir, audit, self._token_counter
            )
        else:
            logger.debug(
                "Skipping breakpoint for %s (another flow paused or not armed)",
                flow.id,
            )
            flow.request.set_text(adapter.outbound_request(curated_ir).decode())

    async def done(self) -> None:
        await bp.clear_all()
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
            self._token_counter = None
            set_counter(None)
            set_recent_auth(None)

    async def response(self, flow: http.HTTPFlow) -> None:
        adapter = flow.metadata.get("manicure_adapter")
        ir = flow.metadata.get("manicure_ir")
        raw_req = flow.metadata.get("manicure_raw_req")
        if adapter is None or ir is None or raw_req is None:
            return

        from manicure.storage import get_storage

        storage = await get_storage()
        curated_ir = flow.metadata.get("manicure_curated_ir", ir)
        audit = flow.metadata.get("manicure_audit")

        exchange_id = str(uuid.uuid4())
        ts = datetime.now(UTC)

        res_text = flow.response.get_text() if flow.response else None
        raw_res = res_text.encode() if res_text else b""
        content_type = (
            flow.response.headers.get("content-type", "") if flow.response else ""
        )

        res_ir, res_stats = _parse_response_ir(
            adapter, raw_res, content_type, exchange_id
        )
        req_stats = _build_req_stats(curated_ir)
        pipeline_stats = _build_pipeline_stats(audit)
        if pipeline_stats is not None and self._token_counter is not None:
            try:
                auth = _relevant_auth_headers(flow.request.headers)
                pipeline_stats = await _stamp_pipeline_tokens(
                    pipeline_stats,
                    ir,
                    curated_ir,
                    adapter,
                    self._token_counter,
                    auth,
                )
            except Exception:
                logger.exception(
                    "count_tokens stamp failed for %s, leaving tokens unset",
                    exchange_id,
                )
        mutated_manually = flow.metadata.get("manicure_mutated_manually", False)

        ts_slug = ts.strftime("%Y%m%dT%H%M%S")
        entry = IndexEntry(
            id=exchange_id,
            ts=ts,
            provider=ir.provider,
            model=ir.model,
            path=f"exchanges/{ts_slug}-{exchange_id[:8]}/",
            req=req_stats,
            pipeline=pipeline_stats,
            res=res_stats,
            mutated_manually=mutated_manually,
        )
        artifacts = ExchangeArtifacts(
            request_raw=raw_req,
            request_ir=ir,
            request_curated_ir=curated_ir if curated_ir != ir else None,
            response_raw=raw_res or None,
            response_ir=res_ir,
        )

        if not await _persist_exchange(storage, entry, artifacts, exchange_id):
            return

        _emit_exchange(
            ir,
            req_stats,
            res_stats,
            exchange_id,
            ts,
            mutated_manually,
            pipeline_stats,
            flow_id=flow.id,
        )


addons = [ManicureAddon()]
