from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from transport_matters.session import exchange_correlation, resource_ids
from transport_matters.session import resource_content_rendering as rendering
from transport_matters.session.resource_content_models import (
    ExchangeRedirectDescriptor,
    JsonContentResponse,
    JsonObject,
    MissingResourceReason,
    MissingResourceResponse,
    ResourceContentResolutionType,
    ResourceContentResponseType,
)

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg.rows import DictRow

    from transport_matters.session.models import SessionRow

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

_WIRE_RESOURCE_SQL_TEMPLATE = """
SELECT e.seq
FROM "event" AS e
JOIN "session" AS s ON s.session_id = e.session_id
WHERE e.session_id = %(session_id)s
  AND s.owner = %(owner)s
  AND (
{exchange_id_containment_sql}
  )
ORDER BY e.seq
LIMIT 1
"""


async def load_resource_content(
    conn: AsyncConnection[DictRow],
    *,
    session: SessionRow,
    owner: str,
    resource_id: str,
    range_start: int | None = None,
    range_end: int | None = None,
    include_debug: bool = False,
) -> ResourceContentResolutionType:
    parsed = resource_ids.parse_resource_id(resource_id)
    if parsed is None:
        return rendering.missing_response(
            resource_id,
            session_id=session.session_id,
            reason="unsupported",
            message="Resource id scheme is not supported.",
            content_provenance=resource_ids.content_provenance_for_id(resource_id),
        )
    if isinstance(parsed, resource_ids.InlineResourceId):
        return await _load_inline_artifact(
            conn,
            session=session,
            owner=owner,
            resource_id=resource_id,
            parsed=parsed,
            range_start=range_start,
            range_end=range_end,
        )
    if isinstance(parsed, resource_ids.NativeResourceId):
        return await _load_native_record(
            conn,
            session=session,
            owner=owner,
            resource_id=resource_id,
            parsed=parsed,
        )
    if isinstance(parsed, resource_ids.WireResourceId):
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


async def _load_inline_artifact(
    conn: AsyncConnection[DictRow],
    *,
    session: SessionRow,
    owner: str,
    resource_id: str,
    parsed: resource_ids.InlineResourceId,
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
        return rendering.missing_response(
            resource_id,
            session_id=session.session_id,
            reason="not-found",
            message="Resource was not found in this session.",
            content_provenance="inline-artifact",
        )
    media_type = rendering.media_type(cast("str | None", row["media_type"]))
    data = bytes(cast("bytes", row["bytes"]))
    provenance = {
        "sessionId": session.session_id,
        "seq": row["seq"],
        "artifactHash": parsed.artifact_hash,
    }
    return rendering.artifact_content_response(
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
    parsed: resource_ids.NativeResourceId,
) -> ResourceContentResponseType:
    if parsed.session_id != session.session_id:
        return rendering.missing_response(
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
        return rendering.missing_response(
            resource_id,
            session_id=session.session_id,
            reason="not-found",
            message="Native record was not found in this session.",
            content_provenance="native-record",
        )
    value = cast("JsonObject", row["raw"])
    text = rendering.json_text(value)
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
        text=rendering.bounded_json_text(text),
        truncated=len(text) > rendering.JSON_TEXT_LIMIT,
    )


async def _load_wire_redirect(
    conn: AsyncConnection[DictRow],
    *,
    session: SessionRow,
    owner: str,
    resource_id: str,
    parsed: resource_ids.WireResourceId,
) -> ResourceContentResolutionType:
    cursor = await conn.execute(
        _wire_resource_sql(),
        _wire_resource_params(
            session_id=session.session_id,
            owner=owner,
            exchange_id=parsed.exchange_id,
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        return rendering.missing_response(
            resource_id,
            session_id=session.session_id,
            reason="uncorrelated",
            message="Wire exchange is not correlated with this session.",
            content_provenance="structured-wire",
        )
    return ExchangeRedirectDescriptor(
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
    return rendering.missing_response(
        resource_id,
        session_id=session_id,
        reason=reason,
        message=message,
        content_provenance="raw-provider-debug",
        provenance={"exchangeId": exchange_id},
    )


def _wire_resource_sql() -> str:
    return _WIRE_RESOURCE_SQL_TEMPLATE.format(
        exchange_id_containment_sql=exchange_correlation.exchange_id_containment_sql("e.ir")
    )


def _wire_resource_params(*, session_id: str, owner: str, exchange_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "owner": owner,
        **exchange_correlation.exchange_id_containment_params(exchange_id),
    }
