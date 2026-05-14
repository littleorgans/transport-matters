"""Codex turn derivation for HTTPS Responses fallback exchanges.

Synthesizes the WS-shaped transport facts that the existing turn
derivation engine consumes, from the HTTP request body and the SSE
response stream of a Codex HTTP fallback flow. The engine then
produces the same `CodexTurnSummary` it does for a WS turn, so the
index entry, derived events, and frontend rendering converge on a
single shape across both transports.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import ValidationError

from transport_matters.codex.derivation_contract import (
    CodexDerivationOperatorFact,
    CodexReplayRequest,
    CodexTransportMessageFact,
    CodexTurnDerivationContext,
)
from transport_matters.codex.derivation_engine import derive_codex_turn_replay
from transport_matters.codex.response_parser import _parse_sse_event_payloads
from transport_matters.storage import CodexTurnListSummary

if TYPE_CHECKING:
    from datetime import datetime


logger = logging.getLogger(__name__)


def derive_codex_http_turn(
    *,
    exchange_id: str,
    raw_request: bytes,
    raw_response: bytes,
    request_headers: dict[str, str] | None = None,
    model: str,
    ts: datetime,
    operator_facts: tuple[CodexDerivationOperatorFact, ...] = (),
) -> CodexTurnListSummary | None:
    """Derive a Codex turn summary for an HTTPS Responses fallback exchange.

    Returns None when the request body is not JSON, the response stream
    has no parseable events, or the derivation engine rejects the
    synthesized facts. Callers treat None as "no codex_turn for this
    row" and leave the index entry field unset.
    """
    try:
        request_payload = json.loads(raw_request)
    except (json.JSONDecodeError, ValueError):
        logger.debug(
            "derive_codex_http_turn: request body is not JSON for %s",
            exchange_id,
        )
        return None
    if not isinstance(request_payload, dict):
        return None
    # Codex HTTP bodies have no top-level `type`; the derivation engine
    # discriminates the turn start by payload_json.type == "response.create".
    # Inject the field on the synthesized client fact so the engine sees
    # the turn open. The wire is unaffected.
    if "type" not in request_payload:
        request_payload = {**request_payload, "type": "response.create"}

    server_payloads = _parse_sse_event_payloads(raw_response)
    if not server_payloads:
        return None

    # HTTP fallback delivers the SSE stream as one buffered body, so all
    # facts share `ts`. The engine orders facts by `message_index`, not
    # by timestamp, but bumping each server fact by one microsecond keeps
    # downstream consumers that compare timestamps monotonic.
    client_fact = CodexTransportMessageFact(
        message_index=0,
        ts=ts,
        direction="client",
        payload_json=request_payload,
    )
    server_facts = tuple(
        CodexTransportMessageFact(
            message_index=i,
            ts=ts + timedelta(microseconds=i),
            direction="server",
            payload_json=payload,
        )
        for i, payload in enumerate(server_payloads, start=1)
    )

    context = CodexTurnDerivationContext(
        exchange_id=exchange_id,
        session_id=exchange_id,
        turn_id=exchange_id,
        turn_index=0,
        request_message_index=0,
        model=model,
    )
    try:
        artifacts = derive_codex_turn_replay(
            CodexReplayRequest(
                context=context,
                transport_messages=(client_fact, *server_facts),
                operator_facts=operator_facts,
                close=None,
            )
        )
    except (ValidationError, ValueError):
        logger.exception(
            "derive_codex_http_turn: derivation failed for %s", exchange_id
        )
        return None
    if artifacts is None:
        return None
    return CodexTurnListSummary.from_turn(artifacts.turn)
