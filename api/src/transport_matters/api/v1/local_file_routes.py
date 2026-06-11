"""Read-only local file content for locator resource panes.

Returns the same ResourceContentResponse JSON the DB resource endpoint emits,
shaped by the shared artifact_content_response pipeline, so the www resource
pane dispatch applies unchanged. Unguarded GET on purpose: same-origin fetches
omit the Origin header; posture matches list_runs.
"""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from transport_matters.session.resource_content_models import (
    ImageContentResponse,
    MissingResourceReason,
    MissingResourceResponse,
    ResourceContentResponse,
)
from transport_matters.session.resource_content_rendering import artifact_content_response

router = APIRouter()

LOCAL_FILE_BYTE_LIMIT = 16 * 1024 * 1024
LOCAL_FILE_RAW_ROUTE = "/local-file/raw"


@router.get("/local-file", response_model=ResourceContentResponse)
async def local_file_content(path: str = Query(min_length=1)) -> object:
    # Blocking pathlib I/O runs off the event loop, matching run_manager's
    # asyncio.to_thread precedent (routes stay async per the api conventions).
    return await asyncio.to_thread(_read_local_file, path)


@router.get(LOCAL_FILE_RAW_ROUTE)
async def local_file_raw(path: str = Query(min_length=1)) -> FileResponse:
    candidate = await asyncio.to_thread(_validated_file, path)
    if candidate is None:
        raise HTTPException(status_code=404, detail="file not found")
    media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return FileResponse(candidate, media_type=media_type)


def _validated_file(path: str) -> Path | None:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.is_dir() or not candidate.is_file():
        return None
    return candidate


def _read_local_file(path: str) -> object:
    candidate = Path(path)
    if not candidate.is_absolute():
        return _missing(path, "unsupported", "path must be absolute")
    if candidate.is_dir():
        return _missing(path, "unsupported", "path is a directory")
    if not candidate.is_file():
        return _missing(path, "not-found", "file not found")
    try:
        size = candidate.stat().st_size
    except OSError:
        return _missing(path, "permission-denied", "file is not readable")
    media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    if media_type.startswith("image/"):
        # Images reference the raw endpoint instead of inlining base64: the
        # browser streams the file natively, so no image is too large and
        # neither the shared IMAGE_BASE64_LIMIT nor the route cap applies.
        return ImageContentResponse(
            id=path,
            title=candidate.name,
            media_type=media_type,
            content_length=size,
            content_provenance="current",
            provenance={"source": "local-file", "path": path},
            url=f"/api{LOCAL_FILE_RAW_ROUTE}?path={quote(path, safe='')}",
            bytes_base64=None,
            width=None,
            height=None,
            alt=candidate.name,
        )
    if size > LOCAL_FILE_BYTE_LIMIT:
        return _missing(path, "too-large", f"file exceeds {LOCAL_FILE_BYTE_LIMIT} bytes")
    try:
        data = candidate.read_bytes()
    except OSError:
        return _missing(path, "permission-denied", "file is not readable")
    return artifact_content_response(
        resource_id=path,
        title=candidate.name,
        media_type=media_type,
        data=data,
        provenance={"source": "local-file", "path": path},
        range_start=None,
        range_end=None,
    )


def _missing(path: str, reason: MissingResourceReason, message: str) -> MissingResourceResponse:
    return MissingResourceResponse(
        id=path,
        title="Missing resource",
        media_type=None,
        content_length=None,
        content_provenance="current",
        provenance={"source": "local-file", "path": path},
        reason=reason,
        message=message,
        retryable=False,
    )
