"""Synthetic IndexEntry and ExchangeArtifacts builders for post-persist sink tests."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from transport_matters.ir import InternalResponse, RequestMetadata, TextBlock, UsageStats
from transport_matters.storage.base import ExchangeArtifacts, IndexEntry, ReqStats
from transport_matters.test_override_support import make_ir

if TYPE_CHECKING:
    from transport_matters.ir import (
        InternalRequest,
        Message,
        SystemPart,
        ThinkingBlock,
        ToolDef,
        ToolUseBlock,
        UnknownBlock,
    )
    from transport_matters.storage.base import ResStats

EXCHANGE_TS = datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC)


def make_request_ir(
    *,
    session_id: str | None = None,
    system: list[SystemPart] | None = None,
    tools: list[ToolDef] | None = None,
    messages: list[Message] | None = None,
) -> InternalRequest:
    base = make_ir(system=system, tools=tools, messages=messages)
    return base.model_copy(update={"metadata": RequestMetadata(session_id=session_id)})


def make_response_ir() -> InternalResponse:
    content: list[TextBlock | ToolUseBlock | ThinkingBlock | UnknownBlock] = [
        TextBlock(text="answer")
    ]
    return InternalResponse(
        id="resp-1", model="claude-3", provider="anthropic", usage=UsageStats(), content=content
    )


def make_index_entry(
    *,
    exchange_id: str = "ex1",
    run_id: str | None = "run1",
    provider: str = "anthropic",
    model: str = "claude-3",
    req: ReqStats | None = None,
    res: ResStats | None = None,
    mutated_manually: bool = False,
) -> IndexEntry:
    return IndexEntry(
        id=exchange_id,
        run_id=run_id,
        ts=EXCHANGE_TS,
        provider=provider,
        model=model,
        path=f"exchanges/x-{exchange_id}/",
        req=req or ReqStats(),
        res=res,
        mutated_manually=mutated_manually,
    )


def make_artifacts(
    request_ir: InternalRequest, response_ir: InternalResponse | None = None
) -> ExchangeArtifacts:
    return ExchangeArtifacts(request_raw=b"{}", request_ir=request_ir, response_ir=response_ir)
