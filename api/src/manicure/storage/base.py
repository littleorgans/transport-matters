"""Abstract storage backend and data models.

Storage backends persist exchange artifacts (raw bodies, IR models)
and the append-only index used by the dashboard.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from manicure.ir import InternalRequest, InternalResponse
from manicure.overrides import (
    OverrideAudit,
)  # explicit re-export
from manicure.overrides import (
    OverrideAuditEntry as OverrideAuditEntry,
)

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


class PipelineStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    overrides_applied: list[OverrideAuditEntry] = Field(default_factory=list)
    chars_before: int = 0
    chars_after: int = 0
    # Authoritative token counts from /v1/messages/count_tokens. Start as
    # None and get stamped asynchronously after the pipeline runs; rows that
    # predate the counter — or for which the endpoint failed — stay None
    # and the UI renders an em dash. Never a chars/4 estimate.
    tokens_before: int | None = None
    tokens_after: int | None = None


class ResStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    text_chars: int = 0
    tool_calls: int = 0


# ── Index entry ─────────────────────────────────────────────────────


class IndexEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    run_id: str | None = None
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
    request_curated_raw: bytes | None = None
    request_curated_ir: InternalRequest | None = None
    request_audit: OverrideAudit | None = None
    response_raw: bytes | None = None
    response_ir: InternalResponse | None = None
    transport: TransportArtifacts | None = None


class TransportHeader(BaseModel):
    name: str
    value: str


class TransportUpgradeArtifacts(BaseModel):
    scheme: str
    host: str
    path: str
    request_headers: list[TransportHeader] = Field(default_factory=list)
    response_status_code: int | None = None
    response_headers: list[TransportHeader] = Field(default_factory=list)


class TransportCloseArtifacts(BaseModel):
    close_code: int | None = None
    close_reason: str | None = None
    closed_by_client: bool | None = None
    initial_client_frame_captured: bool = False
    client_message_count: int = 0
    server_message_count: int = 0


class TransportMessageArtifact(BaseModel):
    direction: Literal["client", "server"]
    is_text: bool
    size_bytes: int
    dropped: bool = False
    event_type: str | None = None
    payload_text: str | None = None
    payload_json: dict[str, Any] | list[Any] | None = None
    payload_base64: str | None = None


class TransportDiagnostic(BaseModel):
    severity: Literal["info", "warning", "error"]
    code: str
    summary: str
    detail: str | None = None
    operator_checks: list[str] = Field(default_factory=list)


class TransportArtifacts(BaseModel):
    provider: str
    protocol: Literal["websocket"] = "websocket"
    upgrade: TransportUpgradeArtifacts
    close: TransportCloseArtifacts | None = None
    messages: list[TransportMessageArtifact] = Field(default_factory=list)


# ── Abstract backend ───────────────────────────────────────────────


class StorageBackend(ABC):
    @abstractmethod
    async def append_index(self, entry: IndexEntry) -> None: ...

    @abstractmethod
    async def persist_exchange(
        self, entry: IndexEntry, artifacts: ExchangeArtifacts
    ) -> None:
        """Persist artifacts plus the matching index row as one operation.

        Implementations must not leave an index row pointing at missing
        artifacts when the write is interrupted or fails.
        """
        ...

    @abstractmethod
    async def upsert_index(self, entry: IndexEntry) -> None:
        """Insert or replace an index row by exchange id."""
        ...

    @abstractmethod
    async def write_exchange(
        self, exchange_id: str, artifacts: ExchangeArtifacts
    ) -> None: ...

    @abstractmethod
    async def read_index(
        self, limit: int, offset: int, run_id: str | None = None
    ) -> list[IndexEntry]: ...

    @abstractmethod
    async def read_exchange(self, exchange_id: str) -> ExchangeArtifacts: ...

    @abstractmethod
    async def read_index_entry(self, exchange_id: str) -> IndexEntry | None: ...

    @abstractmethod
    async def delete_exchange(self, exchange_id: str) -> bool:
        """Delete an exchange index row plus its artifact directory.

        Returns True when either the index row or artifact directory
        existed and was removed. Returns False when the exchange was not
        present at all.
        """
        ...

    @abstractmethod
    async def update_pipeline_tokens(
        self,
        exchange_id: str,
        tokens_before: int | None,
        tokens_after: int | None,
    ) -> IndexEntry | None:
        """Stamp pipeline token counts onto an existing index entry.

        Returns the updated entry on success, or None if the exchange
        does not exist or has no pipeline record. Implementations must
        rewrite the index atomically so a crash mid-write leaves the
        original state intact.
        """
        ...
