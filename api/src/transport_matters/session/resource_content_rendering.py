from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from transport_matters.session.resource_content_models import (
    BinaryContentResponse,
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

TEXT_WINDOW_LIMIT = 64 * 1024
JSON_TEXT_LIMIT = 64 * 1024
IMAGE_BASE64_LIMIT = 1024 * 1024
BINARY_CONTENT_LIMIT = 1024 * 1024


def artifact_content_response(
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


def bounded_json_text(text: str) -> str | None:
    if len(text) <= JSON_TEXT_LIMIT:
        return text
    return text[:JSON_TEXT_LIMIT]


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def media_type(media_type: str | None) -> str:
    if media_type is None or not media_type.strip():
        return "application/octet-stream"
    return media_type.strip().lower()


def missing_response(
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
        text=bounded_json_text(text),
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


def _decode_utf8(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _is_text_media_type(media_type: str) -> bool:
    return media_type.startswith("text/") or media_type in {
        "application/javascript",
        "application/sql",
        "application/xml",
    }


def _is_json_media_type(media_type: str) -> bool:
    return media_type == "application/json" or media_type.endswith("+json")
