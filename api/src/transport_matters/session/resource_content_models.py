from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from transport_matters.session.timeline_models import TimelineModel

JsonObject = dict[str, Any]

ResourceContentProvenance = Literal[
    "current",
    "captured",
    "inline-artifact",
    "structured-wire",
    "raw-provider-debug",
    "native-record",
]
MissingResourceReason = Literal[
    "not-found",
    "outside-workspace",
    "permission-denied",
    "too-large",
    "debug-unavailable",
    "unsupported",
    "uncorrelated",
]
InitialExchangeView = Literal["request", "response", "events", "diagnostics"]


class ResourceContentBase(TimelineModel):
    id: str
    title: str
    media_type: str | None
    content_length: int | None
    content_provenance: ResourceContentProvenance
    provenance: JsonObject


class TextRange(TimelineModel):
    start: int
    end: int
    total: int


class TextContentResponse(ResourceContentBase):
    kind: Literal["text"] = "text"
    text: str
    encoding: Literal["utf-8"] = "utf-8"
    range: TextRange | None
    truncated: bool


class ImageContentResponse(ResourceContentBase):
    kind: Literal["image"] = "image"
    url: str | None
    bytes_base64: str | None
    width: int | None
    height: int | None
    alt: str | None


class BinaryContentResponse(ResourceContentBase):
    kind: Literal["binary"] = "binary"
    download_url: str | None
    sha256: str | None
    too_large: bool


class JsonContentResponse(ResourceContentBase):
    kind: Literal["json"] = "json"
    value: Any
    text: str | None
    truncated: bool


class ExchangeRedirectResponse(ResourceContentBase):
    kind: Literal["exchange-redirect"] = "exchange-redirect"
    exchange_id: str
    route: str | None = None
    initial_view: InitialExchangeView | None


class MissingResourceResponse(ResourceContentBase):
    kind: Literal["missing"] = "missing"
    reason: MissingResourceReason
    message: str
    retryable: bool


ResourceContentResponseType = (
    TextContentResponse
    | ImageContentResponse
    | BinaryContentResponse
    | JsonContentResponse
    | ExchangeRedirectResponse
    | MissingResourceResponse
)
ResourceContentResponse = Annotated[ResourceContentResponseType, Field(discriminator="kind")]
