"""Abstract storage backend and data models.

Storage backends persist exchange artifacts (raw bodies, IR models)
and the append-only index used by the dashboard.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any  # Any: opaque pipeline stats and provider blobs

from pydantic import BaseModel, ConfigDict, Field

from manicure.ir import InternalRequest, InternalResponse

if TYPE_CHECKING:
    from collections.abc import Callable

# ── Stats models ────────────────────────────────────────────────────


class ReqStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    system_parts: int = 0
    system_chars: int = 0
    tools_count: int = 0
    tools_chars: int = 0
    messages_count: int = 0
    messages_chars: int = 0
    total_chars: int = 0


class RuleAuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    action: str
    removed: dict[str, int]  # int: always integers (tools, chars, blocks)


class PipelineStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    rules_applied: list[RuleAuditEntry] = Field(default_factory=list)
    chars_before: int = 0
    chars_after: int = 0
    tokens_approx: int = 0


class ResStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    text_chars: int = 0
    tool_calls: int = 0


# ── Index entry ─────────────────────────────────────────────────────


class IndexEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    ts: datetime
    provider: str
    model: str
    path: str
    req: ReqStats
    pipeline: PipelineStats | None = None
    res: ResStats | None = None
    mutated_manually: bool = False


# ── Exchange artifacts ──────────────────────────────────────────────


class ExchangeArtifacts(BaseModel):
    """All artifacts for a single proxy exchange."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_raw: bytes
    request_ir: InternalRequest
    request_curated_ir: InternalRequest | None = None
    response_raw: bytes | None = None
    response_ir: InternalResponse | None = None


# ── Abstract backend ───────────────────────────────────────────────


class StorageBackend(ABC):
    @abstractmethod
    async def append_index(self, entry: IndexEntry) -> None: ...

    @abstractmethod
    async def write_exchange(
        self, exchange_id: str, artifacts: ExchangeArtifacts
    ) -> None: ...

    @abstractmethod
    async def read_index(self, limit: int, offset: int) -> list[IndexEntry]: ...

    @abstractmethod
    async def read_exchange(self, exchange_id: str) -> ExchangeArtifacts: ...

    @abstractmethod
    async def load_rules(
        self,
    ) -> list[dict[str, Any]]: ...  # Any: rule definitions are opaque

    @abstractmethod
    async def modify_rules(
        self,
        fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    ) -> None:
        """Atomically read, transform, and write rules under a single lock.

        ``fn`` receives the current list (empty if rules.json does not exist),
        must return the replacement list, and may raise to abort the write.
        Implementations must hold the write lock for the entire read→fn→write
        sequence so concurrent callers cannot interleave. This is the only
        write path for rules; no unlocked ``save_rules`` exists.
        """
        ...

    @abstractmethod
    async def read_index_entry(self, exchange_id: str) -> IndexEntry | None: ...
