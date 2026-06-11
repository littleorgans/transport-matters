"""Read-only local file content for locator resource panes.

Returns the same ResourceContentResponse JSON the DB resource endpoint emits,
shaped by the shared artifact_content_response pipeline, so the www resource
pane dispatch applies unchanged. Unguarded GET on purpose: same-origin fetches
omit the Origin header; posture matches list_runs.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Query

from transport_matters.session.resource_content_models import (
    MissingResourceReason,
    MissingResourceResponse,
    ResourceContentResponse,
)
from transport_matters.session.resource_content_rendering import artifact_content_response

router = APIRouter()

LOCAL_FILE_BYTE_LIMIT = 16 * 1024 * 1024


@router.get("/local-file", response_model=ResourceContentResponse)
async def local_file_content(path: str = Query(min_length=1)) -> object:
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
    if size > LOCAL_FILE_BYTE_LIMIT:
        return _missing(path, "too-large", f"file exceeds {LOCAL_FILE_BYTE_LIMIT} bytes")
    try:
        data = candidate.read_bytes()
    except OSError:
        return _missing(path, "permission-denied", "file is not readable")
    media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return artifact_content_response(
        resource_id=path,
        title=candidate.name,
        media_type=media_type,
        data=data,
        provenance={"source": "local-file", "path": path},
        range_start=None,
        range_end=None,
    )


def _missing(
    path: str, reason: MissingResourceReason, message: str
) -> MissingResourceResponse:
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
