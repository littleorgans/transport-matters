"""Shared fixtures and builders for exchanges API tests."""

from datetime import UTC, datetime

from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from transport_matters.overrides import OverrideAudit, OverrideAuditEntry
from transport_matters.storage.base import (
    ExchangeArtifacts,
    IndexEntry,
    PipelineStats,
    ReqStats,
)


def make_index_entry(entry_id: str = "ex-001", *, run_id: str | None = None) -> IndexEntry:
    return IndexEntry(
        id=entry_id,
        run_id=run_id,
        ts=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        provider="anthropic",
        model="anthropic/claude-sonnet-4-20250514",
        path="exchanges/20250601T120000-ex-001/",
        req=ReqStats(
            system_parts=0,
            system_chars=0,
            tools_count=0,
            tools_chars=0,
            messages_count=1,
            messages_chars=2,
            total_chars=2,
        ),
    )


def make_ir() -> InternalRequest:
    return InternalRequest(
        model="anthropic/claude-sonnet-4-20250514",
        provider="anthropic",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


def make_audit() -> OverrideAudit:
    return OverrideAudit(
        entries=[
            OverrideAuditEntry(
                kind="message_text",
                target="msg:0:blk:0",
                applied=True,
                chars_delta=-2,
                curated_value="edited",
            )
        ],
        chars_before=10,
        chars_after=8,
    )


class CountingStub:
    """Counter test double. Returns a preset value and tracks call count."""

    def __init__(self, value: int | None = 42) -> None:
        self.value = value
        self.calls = 0

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
        self.calls += 1
        return self.value


class SeqCountingStub:
    """Counter that returns values in call order; raises if exhausted."""

    def __init__(self, values: list[int | None]) -> None:
        self._values = list(values)
        self._idx = 0
        self.calls = 0

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
        self.calls += 1
        value = self._values[self._idx]
        self._idx += 1
        return value


async def seed_pipeline_entry(
    *,
    exchange_id: str = "ex-pipe",
    provider: str = "anthropic",
    model: str = "anthropic/claude-sonnet-4-20250514",
    tokens_before: int | None = None,
    tokens_after: int | None = None,
    curated_differs: bool = False,
) -> None:
    """Write an index entry with a pipeline record and matching artifacts."""
    from transport_matters.storage import get_storage

    storage = await get_storage()
    entry = make_index_entry(exchange_id).model_copy(
        update={
            "provider": provider,
            "model": model,
            "pipeline": PipelineStats(
                chars_before=100,
                chars_after=80,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
            ),
        }
    )
    ir = make_ir()
    raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
    curated_ir: InternalRequest | None = None
    if curated_differs:
        curated_ir = ir.model_copy(
            update={
                "messages": [
                    Message(role="user", content=[TextBlock(text="edited")]),
                ],
            }
        )
    artifacts = ExchangeArtifacts(
        request_raw=raw,
        request_ir=ir,
        request_curated_ir=curated_ir,
    )
    await storage.append_index(entry)
    await storage.write_exchange(exchange_id, artifacts)


__all__ = [
    "CountingStub",
    "SeqCountingStub",
    "make_audit",
    "make_index_entry",
    "make_ir",
    "seed_pipeline_entry",
]
