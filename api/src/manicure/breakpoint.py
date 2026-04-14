"""Module-level breakpoint state machine.

Supports arming the proxy so the next request pauses mid-flight,
allowing the user to inspect and edit the IR before forwarding.

Runtime imports: nothing from ``manicure``.
TYPE_CHECKING-only: ``manicure.ir.InternalRequest``, ``manicure.overrides.OverrideAudit``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mitmproxy import http

    from manicure.ir import InternalRequest
    from manicure.overrides import OverrideAudit


@dataclass
class PausedFlow:
    flow: http.HTTPFlow
    event: asyncio.Event
    original_ir: InternalRequest
    curated_ir: InternalRequest
    paused_at_ms: int
    audit: OverrideAudit | None = None
    mutated_ir: InternalRequest | None = None
    dropped: bool = False
    # Anthropic auth headers captured at pause time so the FastAPI route
    # layer (which does not have access to the mitmproxy flow directly)
    # can call /v1/messages/count_tokens on the user's behalf when the
    # pipeline is re-audited.
    auth_headers: dict[str, str] = field(default_factory=dict)
    # Authoritative "before" token count — the number of tokens the curated
    # IR would cost if forwarded unchanged. None when the counter failed
    # or is not configured; the UI renders an em dash in that case.
    tokens_before: int | None = None


_mode: Literal["off", "armed_once"] = "off"
_paused: dict[str, PausedFlow] = {}
_lock: asyncio.Lock = asyncio.Lock()
# Serializes breakpoint pauses so concurrent requests queue up one-at-a-time
# instead of all emitting "paused" events simultaneously (which would stomp
# the frontend's singular pausedFlow state).
_pause_serializer: asyncio.Lock = asyncio.Lock()


def arm() -> None:
    global _mode
    _mode = "armed_once"


def disarm() -> None:
    global _mode
    _mode = "off"


def get_mode() -> Literal["off", "armed_once"]:
    return _mode


def is_armed() -> bool:
    return _mode == "armed_once"


def pause_serializer() -> asyncio.Lock:
    """Async lock that serializes breakpoint pauses.

    Hold this lock across the entire pause+await+pop sequence so that only
    one flow is presented to the user at a time. Other incoming requests
    block here until the active one is released.
    """
    return _pause_serializer


async def pause(
    flow: http.HTTPFlow,
    original_ir: InternalRequest,
    curated_ir: InternalRequest,
    audit: OverrideAudit | None = None,
    auth_headers: dict[str, str] | None = None,
) -> asyncio.Event:
    """Register flow, re-arm for next request, return event to await on.

    ``auth_headers`` captures the Anthropic identity on this flow so the
    FastAPI re-audit route can recount tokens without needing access to
    the live mitmproxy flow.
    """
    async with _lock:
        event: asyncio.Event = asyncio.Event()
        _paused[flow.id] = PausedFlow(
            flow=flow,
            event=event,
            original_ir=original_ir,
            curated_ir=curated_ir,
            audit=audit,
            paused_at_ms=int(time.time() * 1000),
            auth_headers=dict(auth_headers) if auth_headers else {},
        )
        return event


async def set_tokens_before(flow_id: str, tokens: int | None) -> bool:
    """Attach a count_tokens result to an already-paused flow.

    Returns False when the flow has been released in the meantime; the
    caller should treat that as a benign race (the UI already moved on).
    """
    async with _lock:
        pf = _paused.get(flow_id)
        if pf is None:
            return False
        pf.tokens_before = tokens
        return True


async def release(flow_id: str, mutated_ir: InternalRequest | None = None) -> bool:
    async with _lock:
        pf = _paused.get(flow_id)
        if pf is None:
            return False
        pf.mutated_ir = mutated_ir
        pf.event.set()
        return True


async def drop(flow_id: str) -> bool:
    async with _lock:
        pf = _paused.get(flow_id)
        if pf is None:
            return False
        pf.dropped = True
        pf.event.set()
        return True


async def pop_paused(flow_id: str) -> PausedFlow | None:
    """Atomically remove and return a paused flow under the lock."""
    async with _lock:
        return _paused.pop(flow_id, None)


async def get_paused() -> dict[str, PausedFlow]:
    """Return a snapshot of paused flows. Safe for iteration."""
    async with _lock:
        return dict(_paused)


async def clear_all() -> None:
    """Drop all paused flows. Called at addon shutdown."""
    async with _lock:
        for pf in _paused.values():
            pf.dropped = True
            pf.event.set()
