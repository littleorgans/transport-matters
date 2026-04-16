"""Meta endpoint: expose the running backend's workspace identity.

The UI uses :func:`GET /api/v1/meta` to resolve the placeholder cwd it
stamps on freshly drafted overlays. The cwd is fixed for the lifetime of
the process (it is the directory from which ``manicure start`` launched),
so the frontend caches this value with ``staleTime: Infinity``.

``workspace_id`` is handed through as an opaque stable string; today the
UI does not act on it, but the apply-at-intercept pipeline will key
overlays by it when that slice lands.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from manicure.config import get_settings
from manicure.workspace import workspace_id as _workspace_id

router = APIRouter()


class MetaResponse(BaseModel):
    cwd: str
    workspace_id: str
    run_id: str | None


@router.get("")
async def get_meta() -> MetaResponse:
    """Return the backend's resolved cwd plus its stable workspace id.

    ``MANICURE_CWD`` (set by ``manicure start`` at invocation time)
    wins over :meth:`Path.cwd` so the result reflects the user's
    launch directory even if the mitmdump process inherited a
    different cwd (e.g. launched from within ``api/``). Falls back to
    the process cwd for direct-uvicorn dev runs where the env var is
    absent.
    """
    settings = get_settings()
    cwd = (settings.cwd or Path.cwd()).resolve()
    wid = _workspace_id(cwd)
    return MetaResponse(
        cwd=str(cwd),
        workspace_id=f"{wid.slug}/{wid.hash}",
        run_id=settings.run_id,
    )
