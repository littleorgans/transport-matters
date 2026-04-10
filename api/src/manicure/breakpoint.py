"""Module-level breakpoint state machine.

Supports arming the proxy so the next request pauses mid-flight,
allowing the user to inspect and edit the IR before forwarding.

This module imports only from ``manicure.ir``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mitmproxy import http

    from manicure.ir import InternalRequest


@dataclass
class PausedFlow:
    flow: http.HTTPFlow
    event: asyncio.Event
    curated_ir: InternalRequest
    paused_at_ms: int
    mutated_ir: InternalRequest | None = None
    dropped: bool = False


_mode: Literal["off", "armed_once"] = "armed_once"
_paused: dict[str, PausedFlow] = {}


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


def pause(flow: http.HTTPFlow, curated_ir: InternalRequest) -> asyncio.Event:
    """Register flow, re-arm for next request, return event to await on."""
    event: asyncio.Event = asyncio.Event()
    _paused[flow.id] = PausedFlow(
        flow=flow,
        event=event,
        curated_ir=curated_ir,
        paused_at_ms=int(time.time() * 1000),
    )
    return event


def release(flow_id: str, mutated_ir: InternalRequest) -> bool:
    pf = _paused.get(flow_id)
    if pf is None:
        return False
    pf.mutated_ir = mutated_ir
    pf.event.set()
    return True


def drop(flow_id: str) -> bool:
    pf = _paused.get(flow_id)
    if pf is None:
        return False
    pf.dropped = True
    pf.event.set()
    return True


def get_paused() -> dict[str, PausedFlow]:
    return _paused


def clear_all() -> None:
    """Drop all paused flows. Called at addon shutdown."""
    for flow_id in list(_paused.keys()):
        drop(flow_id)
