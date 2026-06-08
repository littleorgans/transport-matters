from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from psycopg.types.json import Jsonb

from transport_matters.session.resource_content_models import (
    BinaryContentResponse,
    ExchangeRedirectResponse,
    ImageContentResponse,
    JsonContentResponse,
    JsonObject,
    MissingResourceReason,
    MissingResourceResponse,
    ResourceContentProvenance,
    ResourceContentResponseType,
    TextContentResponse,
    TextRange,
)

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg.rows import DictRow

    from transport_matters.session.models import SessionRow

TEXT_WINDOW_LIMIT = 64 * 1024
JSON_TEXT_LIMIT = 64 * 1024
IMAGE_BASE64_LIMIT = 1024 * 1024
BINARY_CONTENT_LIMIT = 1024 * 1024

_INLINE_ARTIFACT_SQL = """
SELECT a.hash, a.media_type, a.size_bytes, a.bytes, ea.seq, ea.ref
FROM event_artifact AS ea
JOIN artifact AS a ON a.hash = ea.artifact_hash
JOIN "session" AS s ON s.session_id = ea.session_id
WHERE ea.session_id = %(session_id)s
  AND s.owner = %(owner)s
  AND ea.artifact_hash = %(artifact_hash)s
ORDER BY ea.seq
LIMIT 1
"""

_NATIVE_RECORD_SQL = """
SELECT e.seq, e.kind, e.raw, e.source_path, e.source_line, e.created_at
FROM "event" AS e
JOIN "session" AS s ON s.session_id = e.session_id
WHERE e.session_id = %(session_id)s
  AND s.owner = %(owner)s
  AND e.seq = %(seq)s
LIMIT 1
"""

_WIRE_RESOURCE_SQL = """
SELECT e.seq
FROM "event" AS e
JOIN "session" AS s ON s.session_id = e.session_id
WHERE e.session_id = %(session_id)s
  AND s.owner = %(owner)s
  AND (
    e.ir @> %(top_snake)s
    OR e.ir @> %(top_camel)s
    OR e.ir @> %(transport_matters_snake)s
    OR e.ir @> %(transport_matters_camel)s
    OR e.ir @> %(transport_matters_js_snake)s
    OR e.ir @> %(transport_matters_js_camel)s
    OR e.ir @> %(transport_snake)s
    OR e.ir @> %(transport_camel)s
    OR e.ir @> %(wire_snake)s
    OR e.ir @> %(wire_camel)s
    OR e.ir @> %(correlation_snake)s
    OR e.ir @> %(correlation_camel)s
    OR e.ir @> %(turn_snake)s
    OR e.ir @> %(turn_camel)s
  )
ORDER BY e.seq
LIMIT 1
"""


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


async def load_resource_content(
    conn: AsyncConnection[DictRow],
    *,
    session: SessionRow,
    owner: str,
    resource_id: str,
    range_start: int | None = None,
    range_end: int | None = None,
    include_debug: bool = False,
) -> ResourceContentResponseType:
    parsed = _parse_resource_id(resource_id)
    if parsed is None:
        return _missing_response(
            resource_id,
            session_id=session.session_id,
            reason="unsupported",
            message="Resource id scheme is not supported.",
            content_provenance=_content_provenance_for_id(resource_id),
        )
    if isinstance(parsed, InlineResourceId):
        return await _load_inline_artifact(
            conn,
            session=session,
            owner=owner,
            resource_id=resource_id,
            parsed=parsed,
            range_start=range_start,
            range_end=range_end,
        )
    if isinstance(parsed, NativeResourceId):
        return await _load_native_record(
            conn,
            session=session,
            owner=owner,
            resource_id=resource_id,
            parsed=parsed,
        )
    if isinstance(parsed, WireResourceId):
        return await _load_wire_redirect(
            conn,
            session=session,
            owner=owner,
            resource_id=resource_id,
            parsed=parsed,
        )
    return _raw_provider_response(
        resource_id,
        session_id=session.session_id,
        exchange_id=parsed.exchange_id,
        include_debug=include_debug,
    )


def _parse_resource_id(resource_id: str) -> ParsedResourceId | None:
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


async def _load_inline_artifact(
    conn: AsyncConnection[DictRow],
    *,
    session: SessionRow,
    owner: str,
    resource_id: str,
    parsed: InlineResourceId,
    range_start: int | None,
    range_end: int | None,
) -> ResourceContentResponseType:
    cursor = await conn.execute(
        _INLINE_ARTIFACT_SQL,
        {
            "session_id": session.session_id,
            "owner": owner,
            "artifact_hash": parsed.artifact_hash,
        },
    )
    row = await cursor.fetchone()
    if row is None:
        return _missing_response(
            resource_id,
            session_id=session.session_id,
            reason="not-found",
            message="Resource was not found in this session.",
            content_provenance="inline-artifact",
        )
    media_type = _media_type(cast("str | None", row["media_type"]))
    data = bytes(cast("bytes", row["bytes"]))
    provenance = {
        "sessionId": session.session_id,
        "seq": row["seq"],
        "artifactHash": parsed.artifact_hash,
    }
    return _artifact_content_response(
        resource_id=resource_id,
        title="Inline artifact",
        media_type=media_type,
        data=data,
        provenance=provenance,
        range_start=range_start,
        range_end=range_end,
    )


async def _load_native_record(
    conn: AsyncConnection[DictRow],
    *,
    session: SessionRow,
    owner: str,
    resource_id: str,
    parsed: NativeResourceId,
) -> ResourceContentResponseType:
    if parsed.session_id != session.session_id:
        return _missing_response(
            resource_id,
            session_id=session.session_id,
            reason="not-found",
            message="Resource does not belong to this session.",
            content_provenance="native-record",
        )
    cursor = await conn.execute(
        _NATIVE_RECORD_SQL,
        {"session_id": session.session_id, "owner": owner, "seq": parsed.seq},
    )
    row = await cursor.fetchone()
    if row is None:
        return _missing_response(
            resource_id,
            session_id=session.session_id,
            reason="not-found",
            message="Native record was not found in this session.",
            content_provenance="native-record",
        )
    value = cast("JsonObject", row["raw"])
    text = _json_text(value)
    return JsonContentResponse(
        id=resource_id,
        title="Native record",
        media_type="application/json",
        content_length=len(text.encode("utf-8")),
        content_provenance="native-record",
        provenance={
            "sessionId": session.session_id,
            "seq": row["seq"],
            "eventKind": row["kind"],
            "sourcePath": row["source_path"],
            "sourceLine": row["source_line"],
        },
        value=value,
        text=_bounded_json_text(text),
        truncated=len(text) > JSON_TEXT_LIMIT,
    )


async def _load_wire_redirect(
    conn: AsyncConnection[DictRow],
    *,
    session: SessionRow,
    owner: str,
    resource_id: str,
    parsed: WireResourceId,
) -> ResourceContentResponseType:
    cursor = await conn.execute(
        _WIRE_RESOURCE_SQL,
        _wire_resource_params(
            session_id=session.session_id,
            owner=owner,
            exchange_id=parsed.exchange_id,
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        return _missing_response(
            resource_id,
            session_id=session.session_id,
            reason="not-found",
            message="Wire exchange is not correlated with this session.",
            content_provenance="structured-wire",
        )
    return ExchangeRedirectResponse(
        id=resource_id,
        title="Wire exchange",
        media_type=None,
        content_length=None,
        content_provenance="structured-wire",
        provenance={
            "sessionId": session.session_id,
            "seq": row["seq"],
            "exchangeId": parsed.exchange_id,
        },
        exchange_id=parsed.exchange_id,
        route=f"/api/exchanges/{parsed.exchange_id}",
        initial_view="request",
    )


def _raw_provider_response(
    resource_id: str,
    *,
    session_id: str,
    exchange_id: str,
    include_debug: bool,
) -> MissingResourceResponse:
    reason: MissingResourceReason = "unsupported" if include_debug else "debug-unavailable"
    message = (
        "Raw provider debug resources are not implemented for this endpoint."
        if include_debug
        else "Raw provider bytes require explicit debug mode."
    )
    return _missing_response(
        resource_id,
        session_id=session_id,
        reason=reason,
        message=message,
        content_provenance="raw-provider-debug",
        provenance={"exchangeId": exchange_id},
    )


def _artifact_content_response(
    *,
    resource_id: str,
    title: str,
    media_type: str,
    data: bytes,
    provenance: JsonObject,
    range_start: int | None,
    range_end: int | None,
) -> ResourceContentResponseType:
    if _is_json_media_type(media_type):
        return _json_artifact_response(
            resource_id=resource_id,
            title=title,
            media_type=media_type,
            data=data,
            provenance=provenance,
        )
    if _is_text_media_type(media_type):
        text = _decode_utf8(data)
        if text is not None:
            return _text_response(
                resource_id=resource_id,
                title=title,
                media_type=media_type,
                data=data,
                text=text,
                provenance=provenance,
                range_start=range_start,
                range_end=range_end,
            )
    if media_type.startswith("image/"):
        if len(data) > IMAGE_BASE64_LIMIT:
            return _too_large_response(
                resource_id=resource_id,
                title=title,
                media_type=media_type,
                content_length=len(data),
                provenance=provenance,
            )
        return ImageContentResponse(
            id=resource_id,
            title=title,
            media_type=media_type,
            content_length=len(data),
            content_provenance="inline-artifact",
            provenance=provenance,
            url=None,
            bytes_base64=(
                base64.b64encode(data).decode("ascii") if len(data) <= IMAGE_BASE64_LIMIT else None
            ),
            width=None,
            height=None,
            alt=None,
        )
    return _binary_fallback(
        resource_id=resource_id,
        title=title,
        media_type=media_type,
        data=data,
        provenance=provenance,
    )


def _json_artifact_response(
    *,
    resource_id: str,
    title: str,
    media_type: str,
    data: bytes,
    provenance: JsonObject,
) -> ResourceContentResponseType:
    text = _decode_utf8(data)
    if text is None:
        return _binary_fallback(
            resource_id=resource_id,
            title=title,
            media_type=media_type,
            data=data,
            provenance=provenance,
        )
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return _text_response(
            resource_id=resource_id,
            title=title,
            media_type=media_type,
            data=data,
            text=text,
            provenance=provenance,
            range_start=None,
            range_end=None,
        )
    return JsonContentResponse(
        id=resource_id,
        title=title,
        media_type=media_type,
        content_length=len(data),
        content_provenance="inline-artifact",
        provenance=provenance,
        value=value,
        text=_bounded_json_text(text),
        truncated=len(text) > JSON_TEXT_LIMIT,
    )


def _text_response(
    *,
    resource_id: str,
    title: str,
    media_type: str,
    data: bytes,
    text: str,
    provenance: JsonObject,
    range_start: int | None,
    range_end: int | None,
) -> TextContentResponse:
    window, range_, truncated = _text_window(text, range_start=range_start, range_end=range_end)
    return TextContentResponse(
        id=resource_id,
        title=title,
        media_type=media_type,
        content_length=len(data),
        content_provenance="inline-artifact",
        provenance=provenance,
        text=window,
        range=range_,
        truncated=truncated,
    )


def _binary_fallback(
    *,
    resource_id: str,
    title: str,
    media_type: str,
    data: bytes,
    provenance: JsonObject,
) -> ResourceContentResponseType:
    if len(data) > BINARY_CONTENT_LIMIT:
        return _too_large_response(
            resource_id=resource_id,
            title=title,
            media_type=media_type,
            content_length=len(data),
            provenance=provenance,
        )
    return BinaryContentResponse(
        id=resource_id,
        title=title,
        media_type=media_type,
        content_length=len(data),
        content_provenance="inline-artifact",
        provenance=provenance,
        download_url=None,
        sha256=hashlib.sha256(data).hexdigest(),
        too_large=False,
    )


def _too_large_response(
    *,
    resource_id: str,
    title: str,
    media_type: str,
    content_length: int,
    provenance: JsonObject,
) -> MissingResourceResponse:
    return MissingResourceResponse(
        id=resource_id,
        title=title,
        media_type=media_type,
        content_length=content_length,
        content_provenance="inline-artifact",
        provenance=provenance,
        reason="too-large",
        message="Resource exceeds the inline content size cap.",
        retryable=False,
    )


def _text_window(
    text: str, *, range_start: int | None, range_end: int | None
) -> tuple[str, TextRange | None, bool]:
    total = len(text)
    requested_range = range_start is not None or range_end is not None
    start = min(max(range_start or 0, 0), total)
    requested_end = total if range_end is None else min(max(range_end, start), total)
    if not requested_range and total <= TEXT_WINDOW_LIMIT:
        return text, None, False
    end = min(requested_end, start + TEXT_WINDOW_LIMIT)
    truncated = start > 0 or end < total
    return text[start:end], TextRange(start=start, end=end, total=total), truncated


def _bounded_json_text(text: str) -> str | None:
    if len(text) <= JSON_TEXT_LIMIT:
        return text
    return text[:JSON_TEXT_LIMIT]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decode_utf8(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _media_type(media_type: str | None) -> str:
    if media_type is None or not media_type.strip():
        return "application/octet-stream"
    return media_type.strip().lower()


def _is_text_media_type(media_type: str) -> bool:
    return media_type.startswith("text/") or media_type in {
        "application/javascript",
        "application/sql",
        "application/xml",
    }


def _is_json_media_type(media_type: str) -> bool:
    return media_type == "application/json" or media_type.endswith("+json")


def _wire_resource_params(*, session_id: str, owner: str, exchange_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "owner": owner,
        "top_snake": Jsonb({"exchange_id": exchange_id}),
        "top_camel": Jsonb({"exchangeId": exchange_id}),
        "transport_matters_snake": Jsonb({"transport_matters": {"exchange_id": exchange_id}}),
        "transport_matters_camel": Jsonb({"transport_matters": {"exchangeId": exchange_id}}),
        "transport_matters_js_snake": Jsonb({"transportMatters": {"exchange_id": exchange_id}}),
        "transport_matters_js_camel": Jsonb({"transportMatters": {"exchangeId": exchange_id}}),
        "transport_snake": Jsonb({"transport": {"exchange_id": exchange_id}}),
        "transport_camel": Jsonb({"transport": {"exchangeId": exchange_id}}),
        "wire_snake": Jsonb({"wire": {"exchange_id": exchange_id}}),
        "wire_camel": Jsonb({"wire": {"exchangeId": exchange_id}}),
        "correlation_snake": Jsonb({"correlation": {"exchange_id": exchange_id}}),
        "correlation_camel": Jsonb({"correlation": {"exchangeId": exchange_id}}),
        "turn_snake": Jsonb({"turn": {"exchange_id": exchange_id}}),
        "turn_camel": Jsonb({"turn": {"exchangeId": exchange_id}}),
    }


def _content_provenance_for_id(resource_id: str) -> ResourceContentProvenance:
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


def _missing_response(
    resource_id: str,
    *,
    session_id: str,
    reason: MissingResourceReason,
    message: str,
    content_provenance: ResourceContentProvenance,
    provenance: JsonObject | None = None,
) -> MissingResourceResponse:
    merged_provenance = {"sessionId": session_id, "resourceId": resource_id}
    if provenance is not None:
        merged_provenance.update(provenance)
    return MissingResourceResponse(
        id=resource_id,
        title="Missing resource",
        media_type=None,
        content_length=None,
        content_provenance=content_provenance,
        provenance=merged_provenance,
        reason=reason,
        message=message,
        retryable=False,
    )
