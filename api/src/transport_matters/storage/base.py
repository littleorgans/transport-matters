"""Abstract storage backend and data models.

Storage backends persist exchange artifacts (raw bodies, IR models)
and the append-only index used by the dashboard.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from transport_matters.codex.events import (
    CodexSemanticEvent,
    CodexTerminalCause,
    CodexTurnStatus,
    CodexTurnSummary,
)
from transport_matters.ir import InternalRequest, InternalResponse
from transport_matters.overrides import (
    OverrideAudit,
)  # explicit re-export
from transport_matters.overrides import (
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


class CodexTurnListSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_index: int = Field(ge=0)
    message_range_start: int = Field(ge=0)
    message_range_end: int = Field(ge=0)
    status: CodexTurnStatus
    terminal_cause: CodexTerminalCause | None = None
    stop_reason: str | None = None
    text_chars: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)

    @classmethod
    def from_turn(cls, turn: CodexTurnSummary) -> CodexTurnListSummary:
        projected_tool_calls = turn.tool_calls
        if turn.status == "open" and turn.cursor is not None:
            projected_tool_calls += len(turn.cursor.open_tool_calls)
        return cls(
            turn_index=turn.turn_index,
            message_range_start=turn.message_range_start,
            message_range_end=turn.message_range_end,
            status=turn.status,
            terminal_cause=turn.terminal_cause,
            stop_reason=turn.stop_reason,
            text_chars=turn.text_chars,
            tool_calls=projected_tool_calls,
        )


# ── Index entry ─────────────────────────────────────────────────────


class SpawnAnchor(BaseModel):
    model_config = ConfigDict(frozen=True)

    track_spawn_exchange_id: str | None = None
    track_spawn_tool_use_id: str | None = None
    track_spawn_order: int | None = Field(default=None, ge=0)


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
    codex_turn: CodexTurnListSummary | None = None
    mutated_manually: bool = False
    track_id: str | None = None
    parent_track_id: str | None = None
    track_display_name: str | None = None
    track_role: Literal["parent", "subagent"] | None = None
    spawn_anchor: SpawnAnchor | None = None

    @model_validator(mode="after")
    def default_root_track(self) -> IndexEntry:
        if self.track_id is None and self.run_id is not None:
            object.__setattr__(self, "track_id", self.run_id)
        if self.track_role is None and self.parent_track_id is None:
            object.__setattr__(self, "track_role", "parent")
        if self.track_role is None and self.parent_track_id is not None:
            object.__setattr__(self, "track_role", "subagent")
        return self


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
    events: tuple[CodexSemanticEvent, ...] | None = None
    turn: CodexTurnSummary | None = None

    def validate_codex_derived_artifacts(self) -> None:
        """Enforce the shared Codex derivation contract when artifacts exist."""
        if self.events is None and self.turn is None:
            return
        if self.events is None or self.turn is None:
            msg = "Codex derived artifacts require both events and turn"
            raise ValueError(msg)
        from transport_matters.codex.derivation_contract import (
            CodexDerivedTurnArtifacts,
        )

        CodexDerivedTurnArtifacts(events=self.events, turn=self.turn)


class CodexDerivedArtifactFiles(BaseModel):
    model_config = ConfigDict(frozen=True)

    events_jsonl: bytes | None = None
    turn_json: bytes | None = None


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


class TransportHttpRequestArtifacts(BaseModel):
    method: str | None = None
    scheme: str
    host: str
    path: str
    headers: list[TransportHeader] = Field(default_factory=list)


class TransportHttpResponseArtifacts(BaseModel):
    status_code: int | None = None
    headers: list[TransportHeader] = Field(default_factory=list)


class TransportCloseArtifacts(BaseModel):
    ts: datetime | None = None
    close_code: int | None = None
    close_reason: str | None = None
    closed_by_client: bool | None = None
    initial_client_frame_captured: bool = False
    client_message_count: int = 0
    server_message_count: int = 0


class TransportMessageArtifact(BaseModel):
    ts: datetime | None = None
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


def _empty_transport_upgrade() -> TransportUpgradeArtifacts:
    return TransportUpgradeArtifacts(scheme="", host="", path="")


class TransportArtifacts(BaseModel):
    provider: str
    protocol: Literal["websocket", "http"] = "websocket"
    upgrade: TransportUpgradeArtifacts = Field(default_factory=_empty_transport_upgrade)
    request: TransportHttpRequestArtifacts | None = None
    response: TransportHttpResponseArtifacts | None = None
    close: TransportCloseArtifacts | None = None
    messages: list[TransportMessageArtifact] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def serialize_by_protocol(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        data = dict(cast("dict[str, Any]", handler(self)))
        if self.protocol == "websocket":
            data.pop("request", None)
            data.pop("response", None)
        else:
            data.pop("upgrade", None)
            data.pop("close", None)
        return data


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
        self,
        limit: int,
        offset: int,
        run_id: str | None = None,
        track_id: str | None = None,
    ) -> list[IndexEntry]: ...

    @abstractmethod
    async def read_exchange(self, exchange_id: str) -> ExchangeArtifacts: ...

    @abstractmethod
    async def read_codex_derived_files(
        self, exchange_id: str
    ) -> CodexDerivedArtifactFiles: ...

    @abstractmethod
    async def write_codex_derived_artifacts(
        self, exchange_id: str, artifacts: ExchangeArtifacts
    ) -> None: ...

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
