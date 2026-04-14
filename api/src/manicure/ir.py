"""Internal representation models for the context control plane.

These models are the canonical interchange format between adapters,
pipeline rules, storage, and the breakpoint editor. All IR models are
frozen (immutable); pipeline stages produce new instances.

This module imports nothing from ``manicure``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal  # Any: used for opaque provider blobs

from pydantic import BaseModel, ConfigDict, Field

# ── Content blocks ──────────────────────────────────────────────────


class TextBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]  # Any: arbitrary tool input schema


class ToolResultBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: list[TextBlock | ImageBlock]
    is_error: bool = False


class ThinkingBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["thinking"] = "thinking"
    text: str
    provider_data: dict[str, Any] | None = None  # Any: opaque provider blob


class ImageBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["image"] = "image"
    source: dict[str, Any]  # Any: provider-specific image encoding


class UnknownBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["unknown"] = "unknown"
    raw: dict[str, Any]  # Any: unrecognised block preserved verbatim


ContentBlock = Annotated[
    TextBlock
    | ToolUseBlock
    | ToolResultBlock
    | ThinkingBlock
    | ImageBlock
    | UnknownBlock,
    Field(discriminator="type"),
]

# ── Request components ──────────────────────────────────────────────


class SystemPart(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["text"] = "text"
    text: str
    cache_hint: dict[str, Any] | None = (
        None  # Any: adapter-opaque, preserved on round-trip
    )
    provider_data: dict[str, Any] | None = None  # Any: extra provider fields


class ToolDef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any]  # Any: JSON Schema object
    provider_data: dict[str, Any] | None = None  # Any: extra provider fields


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant"]
    content: list[ContentBlock]


class SamplingParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_tokens: int
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop_sequences: list[str] = Field(default_factory=list)


class RequestMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str | None = None
    device_id: str | None = None
    account_id: str | None = None
    provider_metadata: dict[str, Any] = Field(  # Any: adapter-specific, opaque to core
        default_factory=dict,
    )


# ── Top-level IR models ────────────────────────────────────────────


class InternalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    provider: str
    system: list[SystemPart]
    tools: list[ToolDef]
    messages: list[Message] = Field(min_length=1)
    sampling: SamplingParams
    metadata: RequestMetadata
    stream: bool = False
    provider_extras: dict[str, Any] = (
        Field(  # Any: catch-all for provider-only top-level fields
            default_factory=dict,
        )
    )


class UsageStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class InternalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    model: str
    provider: str
    stop_reason: str | None = None
    usage: UsageStats
    content: list[TextBlock | ToolUseBlock | ThinkingBlock | UnknownBlock]
    provider_extras: dict[str, Any] = Field(  # Any: catch-all for provider-only fields
        default_factory=dict,
    )


# Rebuild all models so forward references (e.g. ImageBlock inside
# ToolResultBlock) are fully resolved.
ToolResultBlock.model_rebuild()
Message.model_rebuild()
InternalRequest.model_rebuild()
InternalResponse.model_rebuild()
