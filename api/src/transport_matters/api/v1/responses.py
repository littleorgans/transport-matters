"""Shared response helpers for API v1 routes."""

from __future__ import annotations

import base64
import binascii
import json
from typing import TYPE_CHECKING, NoReturn, cast

from fastapi import status as http_status

from transport_matters.api.v1.errors import raise_api_error

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import BaseModel


def response_payload(response: BaseModel, *, exclude_none: bool = True) -> dict[str, object]:
    return cast(
        "dict[str, object]",
        response.model_dump(mode="json", by_alias=True, exclude_none=exclude_none),
    )


def raise_not_found(code: str, message: str) -> NoReturn:
    raise_api_error(http_status.HTTP_404_NOT_FOUND, code, message)


def encode_cursor(
    offset: int,
    *,
    filters: Mapping[str, object] | None = None,
    strip_padding: bool = True,
) -> str:
    payload: dict[str, object] = {"offset": offset}
    if filters is not None:
        payload["filters"] = dict(filters)
    raw = json.dumps(payload, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode()
    return encoded.rstrip("=") if strip_padding else encoded


def decode_cursor(
    cursor: str,
    *,
    filters: Mapping[str, object] | None = None,
    strip_padding: bool = True,
) -> int:
    try:
        encoded = cursor + "=" * (-len(cursor) % 4) if strip_padding else cursor
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode()).decode())
    except binascii.Error, UnicodeError, ValueError, json.JSONDecodeError:
        raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    if not isinstance(payload, dict):
        raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    if filters is not None and payload.get("filters") != filters:
        raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_cursor",
            "cursor does not match the active filters",
        )
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    return offset
