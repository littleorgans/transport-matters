"""Codex turn derivation for HTTPS Responses fallback exchanges.

Synthesizes the WS-shaped transport facts that the existing turn
derivation engine consumes, from the HTTP request body and the SSE
response stream of a Codex HTTP fallback flow. The engine then
produces the same `CodexTurnSummary` it does for a WS turn, so the
index entry, derived events, and frontend rendering converge on a
single shape across both transports.
"""

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import ValidationError

from transport_matters.codex.continuity import (
    allocate_codex_continuity_from_headers,
    get_codex_continuity_allocator,
)
from transport_matters.codex.derivation_contract import (
    CodexDerivationOperatorFact,
    CodexDerivedTurnArtifacts,
    CodexReplayRequest,
    CodexTransportMessageFact,
    CodexTurnDerivationContext,
)
from transport_matters.codex.derivation_engine import derive_codex_turn_replay
from transport_matters.codex.transport import parse_codex_http_transport_payloads

if TYPE_CHECKING:
    from datetime import datetime


logger = logging.getLogger(__name__)


def _codex_http_turn_context(
    *,
    exchange_id: str,
    request_headers: dict[str, str] | None,
    model: str,
) -> CodexTurnDerivationContext:
    allocation = (
        allocate_codex_continuity_from_headers(
            get_codex_continuity_allocator(),
            request_headers.get,
        )
        if request_headers is not None
        else None
    )
    session_id = exchange_id
    turn_id = exchange_id
    turn_index = 0
    if allocation is not None:
        session_id = allocation.session_id
        turn_id = allocation.turn_id or exchange_id
        turn_index = allocation.turn_index
    return CodexTurnDerivationContext(
        exchange_id=exchange_id,
        session_id=session_id,
        turn_id=turn_id,
        turn_index=turn_index,
        request_message_index=0,
        model=model,
    )


def derive_codex_http_turn(
    *,
    exchange_id: str,
    raw_request: bytes,
    raw_response: bytes,
    request_headers: dict[str, str] | None = None,
    model: str,
    ts: datetime,
    operator_facts: tuple[CodexDerivationOperatorFact, ...] = (),
) -> CodexDerivedTurnArtifacts | None:
    """Derive Codex turn artifacts for an HTTPS Responses fallback exchange.

    Returns None when the request body is not JSON, the response stream
    has no parseable events, or the derivation engine rejects the
    synthesized facts. Callers project the index summary from the
    returned turn and persist the full artifact sidecars.
    """
    payloads = parse_codex_http_transport_payloads(raw_request, raw_response)
    if payloads.request is None:
        logger.debug(
            "derive_codex_http_turn: request body is not JSON for %s",
            exchange_id,
        )
        return None
    if not payloads.response_events:
        return None

    # HTTP fallback delivers the SSE stream as one buffered body, so all
    # facts share `ts`. The engine orders facts by `message_index`, not
    # by timestamp, but bumping each server fact by one microsecond keeps
    # downstream consumers that compare timestamps monotonic.
    client_fact = CodexTransportMessageFact(
        message_index=0,
        ts=ts,
        direction="client",
        payload_json=payloads.request,
    )
    server_facts = tuple(
        CodexTransportMessageFact(
            message_index=i,
            ts=ts + timedelta(microseconds=i),
            direction="server",
            payload_json=payload,
        )
        for i, payload in enumerate(payloads.response_events, start=1)
    )

    context = _codex_http_turn_context(
        exchange_id=exchange_id,
        request_headers=request_headers,
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
    except ValidationError, ValueError:
        logger.exception("derive_codex_http_turn: derivation failed for %s", exchange_id)
        return None
    return artifacts
