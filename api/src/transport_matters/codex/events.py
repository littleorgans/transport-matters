"""Codex turn-scoped semantic artifact models."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from transport_matters.codex.json_utils import canonicalize_json

type CodexEventSource = Literal["client", "server", "proxy", "operator"]
type CodexSemanticEventKind = Literal[
    "turn_started",
    "request_curated",
    "breakpoint_paused",
    "breakpoint_released",
    "assistant_item_completed",
    "tool_call_completed",
    "tool_output_submitted",
    "response_completed",
    "response_failed",
    "turn_finalized",
]
type CodexTurnStatus = Literal["open", "completed", "failed", "interrupted"]
type CodexTerminalCause = Literal[
    "response_completed",
    "response_failed",
    "websocket_close",
]


class CodexTransportRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_index: int = Field(ge=0)


class CodexOpenAssistantItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = ""


class CodexOpenToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arguments: str = ""


class CodexDerivationCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    next_message_index: int = Field(ge=0)
    next_seq: int = Field(ge=0)
    open_assistant_items: dict[str, CodexOpenAssistantItem] = Field(default_factory=dict)
    open_tool_calls: dict[str, CodexOpenToolCall] = Field(default_factory=dict)
    terminal_seen: bool = False

    @field_validator("open_assistant_items", "open_tool_calls", mode="before")
    @classmethod
    def _sort_cursor_maps(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {key: value[key] for key in sorted(value)}


class CodexSemanticEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    exchange_id: str
    session_id: str
    turn_id: str
    seq: int = Field(ge=0)
    ts: datetime
    source: CodexEventSource
    kind: CodexSemanticEventKind
    transport_ref: CodexTransportRef | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    derivation_version: int = Field(ge=0)

    @field_validator("data", mode="before")
    @classmethod
    def _canonicalize_data(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return canonicalize_json(value)


class CodexTurnSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str
    exchange_id: str
    session_id: str
    turn_index: int = Field(ge=0)
    request_message_index: int = Field(ge=0)
    terminal_message_index: int | None = Field(default=None, ge=0)
    terminal_cause: CodexTerminalCause | None = None
    message_range_start: int = Field(ge=0)
    message_range_end: int = Field(ge=0)
    model: str
    status: CodexTurnStatus
    stop_reason: str | None = None
    text_chars: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    started_at: datetime
    ended_at: datetime | None = None
    derivation_version: int = Field(ge=0)
    cursor: CodexDerivationCursor | None = None

    @model_validator(mode="after")
    def _validate_ranges(self) -> CodexTurnSummary:
        if self.request_message_index != self.message_range_start:
            msg = "request_message_index must match message_range_start"
            raise ValueError(msg)
        if self.message_range_end < self.message_range_start:
            msg = "message_range_end must be >= message_range_start"
            raise ValueError(msg)
        if (
            self.terminal_message_index is not None
            and self.terminal_message_index < self.message_range_start
        ):
            msg = "terminal_message_index must be within the turn message range"
            raise ValueError(msg)
        if (
            self.terminal_message_index is not None
            and self.terminal_message_index > self.message_range_end
        ):
            msg = "terminal_message_index must be within the turn message range"
            raise ValueError(msg)
        if self.status == "open":
            if self.terminal_message_index is not None or self.terminal_cause is not None:
                msg = "open turns cannot carry terminal markers"
                raise ValueError(msg)
            if self.ended_at is not None:
                msg = "open turns cannot carry ended_at"
                raise ValueError(msg)
            if self.stop_reason is not None:
                msg = "open turns cannot carry stop_reason"
                raise ValueError(msg)
            return self

        if self.ended_at is None:
            msg = "finalized turns must carry ended_at"
            raise ValueError(msg)
        if self.terminal_cause is None:
            msg = "finalized turns must carry terminal_cause"
            raise ValueError(msg)

        if self.status == "completed":
            if self.terminal_cause != "response_completed":
                msg = "completed turns must use response_completed terminal_cause"
                raise ValueError(msg)
            if self.terminal_message_index is None:
                msg = "completed turns must carry terminal_message_index"
                raise ValueError(msg)
            if self.stop_reason is None:
                msg = "completed turns must carry stop_reason"
                raise ValueError(msg)
            return self

        if self.status == "failed":
            if self.terminal_cause != "response_failed":
                msg = "failed turns must use response_failed terminal_cause"
                raise ValueError(msg)
            if self.terminal_message_index is None:
                msg = "failed turns must carry terminal_message_index"
                raise ValueError(msg)
            if self.stop_reason is None:
                msg = "failed turns must carry stop_reason"
                raise ValueError(msg)
            return self

        if self.terminal_cause != "websocket_close":
            msg = "interrupted turns must use websocket_close terminal_cause"
            raise ValueError(msg)
        if self.terminal_message_index is not None:
            msg = "interrupted turns cannot carry terminal_message_index"
            raise ValueError(msg)
        if self.stop_reason is None:
            msg = "interrupted turns must carry stop_reason"
            raise ValueError(msg)
        return self


__all__ = [
    "CodexDerivationCursor",
    "CodexEventSource",
    "CodexOpenAssistantItem",
    "CodexOpenToolCall",
    "CodexSemanticEvent",
    "CodexSemanticEventKind",
    "CodexTerminalCause",
    "CodexTransportRef",
    "CodexTurnStatus",
    "CodexTurnSummary",
]
