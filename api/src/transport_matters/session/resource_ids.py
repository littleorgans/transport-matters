from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from transport_matters.session.resource_content_models import ResourceContentProvenance


@dataclass(frozen=True)
class InlineResourceId:
    artifact_hash: str


@dataclass(frozen=True)
class NativeResourceId:
    session_id: str
    seq: int


@dataclass(frozen=True)
class WireResourceId:
    exchange_id: str


@dataclass(frozen=True)
class RawProviderResourceId:
    exchange_id: str


ParsedResourceId = InlineResourceId | NativeResourceId | WireResourceId | RawProviderResourceId


def inline_resource_id(artifact_hash: str) -> str:
    return f"inline:{artifact_hash}"


def native_resource_id(session_id: str, seq: int) -> str:
    return f"native:{session_id}:{seq}"


def wire_resource_id(exchange_id: str) -> str:
    return f"wire:{exchange_id}"


def raw_provider_resource_id(exchange_id: str) -> str:
    return f"raw-provider:{exchange_id}"


def parse_resource_id(resource_id: str) -> ParsedResourceId | None:
    parts = resource_id.split(":")
    if len(parts) == 2 and parts[0] == "inline" and parts[1]:
        return InlineResourceId(artifact_hash=parts[1])
    if len(parts) == 3 and parts[0] == "native" and parts[1] and parts[2].isdigit():
        return NativeResourceId(session_id=parts[1], seq=int(parts[2]))
    if len(parts) == 2 and parts[0] == "wire" and parts[1]:
        return WireResourceId(exchange_id=parts[1])
    if len(parts) == 2 and parts[0] == "raw-provider" and parts[1]:
        return RawProviderResourceId(exchange_id=parts[1])
    return None


def content_provenance_for_id(resource_id: str) -> ResourceContentProvenance:
    scheme = resource_id.split(":", 1)[0]
    if scheme == "inline":
        return "inline-artifact"
    if scheme == "wire":
        return "structured-wire"
    if scheme == "native":
        return "native-record"
    if scheme == "file-captured":
        return "captured"
    if scheme == "raw-provider":
        return "raw-provider-debug"
    return "current"
