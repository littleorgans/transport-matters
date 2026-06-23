"""Shared API error helpers."""

from __future__ import annotations

from typing import NoReturn, cast

from fastapi import HTTPException

from transport_matters.api.v1.session_models import ApiError


def api_error(code: str, message: str, details: object | None = None) -> dict[str, object]:
    payload = ApiError(code=code, message=message, details=details).model_dump(
        mode="json",
        exclude_none=True,
    )
    return cast("dict[str, object]", payload)


def raise_api_error(
    status_code: int,
    code: str,
    message: str,
    details: object | None = None,
) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=api_error(code, message, details))
