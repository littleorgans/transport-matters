"""Codex derivation contract models and version helpers."""

from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from transport_matters.codex.events import (
    CodexDerivationCursor,
    CodexSemanticEvent,
    CodexTurnSummary,
)
from transport_matters.codex.json_utils import canonicalize_json

type CodexDerivationVersion = Literal[1]
type CodexDerivationOperatorFactKind = Literal[
    "request_curated",
    "breakpoint_paused",
    "breakpoint_released",
]
type CodexTransportDirection = Literal["client", "server"]

CODEX_DERIVATION_VERSION: CodexDerivationVersion = 1
SUPPORTED_CODEX_DERIVATION_VERSIONS = frozenset({CODEX_DERIVATION_VERSION})
CODEX_INITIAL_EVENT_SEQ = 1
CODEX_EVENT_ID_WIDTH = 6
CODEX_EVENT_ID_PREFIX = "evt_"
_OPERATOR_FACT_PRECEDENCE: dict[CodexDerivationOperatorFactKind, int] = {
    "request_curated": 1,
    "breakpoint_paused": 2,
    "breakpoint_released": 3,
}


class UnsupportedCodexDerivationVersionError(ValueError):
    """Raised when derived artifacts use an unsupported contract version."""


def is_supported_codex_derivation_version(version: int) -> bool:
    return version in SUPPORTED_CODEX_DERIVATION_VERSIONS


def require_supported_codex_derivation_version(version: int) -> int:
    if is_supported_codex_derivation_version(version):
        return version
    supported = ", ".join(str(value) for value in sorted(SUPPORTED_CODEX_DERIVATION_VERSIONS))
    msg = f"Unsupported Codex derivation version {version}. Supported versions: {supported}"
    raise UnsupportedCodexDerivationVersionError(msg)


def codex_next_event_seq(cursor: CodexDerivationCursor | None) -> int:
    if cursor is None:
        return CODEX_INITIAL_EVENT_SEQ
    if cursor.next_seq < CODEX_INITIAL_EVENT_SEQ:
        msg = "cursor.next_seq must be >= 1"
        raise ValueError(msg)
    return cursor.next_seq


def codex_event_id_for_seq(seq: int) -> str:
    if seq < CODEX_INITIAL_EVENT_SEQ:
        msg = "event seq must be >= 1"
        raise ValueError(msg)
    return f"{CODEX_EVENT_ID_PREFIX}{seq:0{CODEX_EVENT_ID_WIDTH}d}"


def codex_event_ts(
    *,
    transport_message: CodexTransportMessageFact | None = None,
    operator_fact: CodexDerivationOperatorFact | None = None,
) -> datetime:
    selected = [value for value in (transport_message, operator_fact) if value is not None]
    if len(selected) != 1:
        msg = "exactly one source fact is required to assign a deterministic event timestamp"
        raise ValueError(msg)
    return selected[0].ts


class CodexTransportMessageFact(BaseModel):
    """Minimal transport fact needed by the pure turn deriver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_index: int = Field(ge=0)
    ts: datetime
    direction: CodexTransportDirection
    event_type: str | None = None
    payload_json: dict[str, Any] | list[Any] | None = None
    dropped: bool = False

    @model_validator(mode="before")
    @classmethod
    def _derive_event_type(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload_json = value.get("payload_json")
        event_type = value.get("event_type")
        payload_event_type = None
        if isinstance(payload_json, dict):
            nested = payload_json.get("type")
            if isinstance(nested, str):
                payload_event_type = nested
        if event_type is None and payload_event_type is not None:
            return value | {"event_type": payload_event_type}
        if (
            isinstance(event_type, str)
            and payload_event_type is not None
            and event_type != payload_event_type
        ):
            msg = "event_type must match payload_json.type when both are present"
            raise ValueError(msg)
        return value

    @field_validator("payload_json", mode="before")
    @classmethod
    def _canonicalize_payload_json(
        cls,
        value: dict[str, Any] | list[Any] | None,
    ) -> dict[str, Any] | list[Any] | None:
        if value is None:
            return None
        return cast("dict[str, Any] | list[Any]", canonicalize_json(value))


class CodexTransportCloseFact(BaseModel):
    """Deterministic websocket close fact used for interrupted turns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ts: datetime
    close_code: int | None = None
    close_reason: str | None = None


class CodexDerivationOperatorFact(BaseModel):
    """Persisted local metadata that becomes semantic events at turn start."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: CodexDerivationOperatorFactKind
    ts: datetime
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def _canonicalize_data(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return canonicalize_json(value)


class CodexTurnDerivationContext(BaseModel):
    """Turn identity and fixed metadata shared by replay and incremental advance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exchange_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    turn_index: int = Field(ge=0)
    request_message_index: int = Field(ge=0)
    model: str = Field(min_length=1)
    derivation_version: int = CODEX_DERIVATION_VERSION

    @field_validator("derivation_version")
    @classmethod
    def _validate_derivation_version(cls, value: int) -> int:
        return require_supported_codex_derivation_version(value)


class _CodexDerivationRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context: CodexTurnDerivationContext
    transport_messages: tuple[CodexTransportMessageFact, ...] = ()
    operator_facts: tuple[CodexDerivationOperatorFact, ...] = ()
    close: CodexTransportCloseFact | None = None

    @field_validator("transport_messages", mode="before")
    @classmethod
    def _coerce_transport_messages(
        cls,
        value: Any,
    ) -> tuple[CodexTransportMessageFact, ...]:
        if value in (None, ()):
            return ()
        return tuple(value)

    @field_validator("operator_facts", mode="before")
    @classmethod
    def _coerce_operator_facts(
        cls,
        value: Any,
    ) -> tuple[CodexDerivationOperatorFact, ...]:
        if value in (None, ()):
            return ()
        return tuple(value)

    @field_validator("operator_facts", mode="after")
    @classmethod
    def _sort_operator_facts(
        cls,
        value: tuple[CodexDerivationOperatorFact, ...],
    ) -> tuple[CodexDerivationOperatorFact, ...]:
        return tuple(
            sorted(
                value,
                key=lambda fact: (
                    fact.ts,
                    _OPERATOR_FACT_PRECEDENCE[fact.kind],
                ),
            )
        )

    @model_validator(mode="after")
    def _validate_transport_messages(self) -> _CodexDerivationRequestBase:
        previous_index: int | None = None
        for message in self.transport_messages:
            if previous_index is not None and message.message_index <= previous_index:
                msg = "transport_messages must be strictly ordered by message_index"
                raise ValueError(msg)
            previous_index = message.message_index

        seen_operator_kinds: set[CodexDerivationOperatorFactKind] = set()
        for fact in self.operator_facts:
            if fact.kind in seen_operator_kinds:
                msg = f"operator_facts cannot repeat kind {fact.kind}"
                raise ValueError(msg)
            seen_operator_kinds.add(fact.kind)

        return self


class CodexReplayRequest(_CodexDerivationRequestBase):
    """Full replay input from the turn start transport boundary."""

    @model_validator(mode="after")
    def _validate_replay_start(self) -> CodexReplayRequest:
        if not self.transport_messages:
            msg = "replay requires at least one transport message"
            raise ValueError(msg)
        first_index = self.transport_messages[0].message_index
        if first_index != self.context.request_message_index:
            msg = "replay must begin at context.request_message_index"
            raise ValueError(msg)
        return self


class CodexIncrementalAdvanceRequest(_CodexDerivationRequestBase):
    """Incremental derivation input from persisted open turn cursor state."""

    cursor: CodexDerivationCursor
    started_at: datetime | None = None
    text_chars: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_incremental_advance(self) -> CodexIncrementalAdvanceRequest:
        codex_next_event_seq(self.cursor)
        if self.cursor.terminal_seen:
            msg = "incremental advance cannot resume from a terminal cursor"
            raise ValueError(msg)
        if not self.transport_messages:
            if (
                self.cursor.next_message_index > self.context.request_message_index
                and self.started_at is None
            ):
                msg = "incremental advance requires started_at once the turn has started"
                raise ValueError(msg)
            return self
        first_index = self.transport_messages[0].message_index
        if first_index != self.cursor.next_message_index:
            msg = "incremental advance must begin at cursor.next_message_index"
            raise ValueError(msg)
        if (
            self.cursor.next_message_index > self.context.request_message_index
            and self.started_at is None
        ):
            msg = "incremental advance requires started_at once the turn has started"
            raise ValueError(msg)
        return self


class CodexDerivedTurnArtifacts(BaseModel):
    """Semantic artifacts emitted by either replay or incremental advance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    events: tuple[CodexSemanticEvent, ...] = ()
    turn: CodexTurnSummary

    @field_validator("events", mode="before")
    @classmethod
    def _coerce_events(cls, value: Any) -> tuple[CodexSemanticEvent, ...]:
        if value in (None, ()):
            return ()
        return tuple(value)

    @model_validator(mode="after")
    def _validate_artifacts(self) -> CodexDerivedTurnArtifacts:
        require_supported_codex_derivation_version(self.turn.derivation_version)

        previous_seq: int | None = None
        for event in self.events:
            if event.exchange_id != self.turn.exchange_id:
                msg = "event exchange_id must match turn.exchange_id"
                raise ValueError(msg)
            if event.session_id != self.turn.session_id:
                msg = "event session_id must match turn.session_id"
                raise ValueError(msg)
            if event.turn_id != self.turn.turn_id:
                msg = "event turn_id must match turn.turn_id"
                raise ValueError(msg)
            if event.derivation_version != self.turn.derivation_version:
                msg = "event derivation_version must match turn.derivation_version"
                raise ValueError(msg)
            if event.event_id != codex_event_id_for_seq(event.seq):
                msg = "event_id must be derived from seq via codex_event_id_for_seq"
                raise ValueError(msg)
            if previous_seq is not None and event.seq != previous_seq + 1:
                msg = "events must use contiguous seq values"
                raise ValueError(msg)
            previous_seq = event.seq

        if self.turn.status != "open":
            return self

        cursor = self.turn.cursor
        if cursor is None:
            msg = "open turn summaries must carry cursor state"
            raise ValueError(msg)
        if cursor.terminal_seen:
            msg = "open turn cursors cannot mark terminal_seen"
            raise ValueError(msg)
        expected_next_message_index = self.turn.message_range_end + 1
        if cursor.next_message_index != expected_next_message_index:
            msg = "open turn cursor.next_message_index must equal turn.message_range_end + 1"
            raise ValueError(msg)
        expected_next_seq = CODEX_INITIAL_EVENT_SEQ if previous_seq is None else previous_seq + 1
        if cursor.next_seq != expected_next_seq:
            msg = "open turn cursor.next_seq must equal the next contiguous event seq"
            raise ValueError(msg)
        return self


__all__ = [
    "CODEX_DERIVATION_VERSION",
    "CODEX_EVENT_ID_PREFIX",
    "CODEX_EVENT_ID_WIDTH",
    "CODEX_INITIAL_EVENT_SEQ",
    "SUPPORTED_CODEX_DERIVATION_VERSIONS",
    "CodexDerivationOperatorFact",
    "CodexDerivationOperatorFactKind",
    "CodexDerivationVersion",
    "CodexDerivedTurnArtifacts",
    "CodexIncrementalAdvanceRequest",
    "CodexReplayRequest",
    "CodexTransportCloseFact",
    "CodexTransportDirection",
    "CodexTransportMessageFact",
    "CodexTurnDerivationContext",
    "UnsupportedCodexDerivationVersionError",
    "codex_event_id_for_seq",
    "codex_event_ts",
    "codex_next_event_seq",
    "is_supported_codex_derivation_version",
    "require_supported_codex_derivation_version",
]
