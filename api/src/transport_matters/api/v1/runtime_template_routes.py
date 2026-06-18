"""Runtime template browse endpoint."""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, NoReturn, cast

from fastapi import APIRouter, HTTPException
from fastapi import status as http_status

from transport_matters.api.v1.session_models import ApiError
from transport_matters.runtime_registry import (
    RuntimeTemplateRegistryError,
    list_runtime_templates,
)

if TYPE_CHECKING:
    from transport_matters.runtime_templates import RuntimeTemplateSummary

router = APIRouter()


def _api_error(code: str, message: str, details: object | None = None) -> dict[str, object]:
    payload = ApiError(code=code, message=message, details=details).model_dump(
        mode="json",
        exclude_none=True,
    )
    return cast("dict[str, object]", payload)


def _raise_api_error(
    status_code: int,
    code: str,
    message: str,
    details: object | None = None,
) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=_api_error(code, message, details))


def _summary_payload(summary: RuntimeTemplateSummary) -> dict[str, object]:
    payload = summary.model_dump(mode="json", exclude_none=True)
    payload.setdefault("recommended_model", None)
    return cast("dict[str, object]", payload)


@router.get("/runtime-templates")
async def get_runtime_templates() -> dict[str, object]:
    try:
        templates = await asyncio.to_thread(list_runtime_templates, env=os.environ)
    except RuntimeTemplateRegistryError as exc:
        _raise_api_error(
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "runtime_template_registry_error",
            str(exc),
        )
    return {"items": [_summary_payload(template) for template in templates]}
