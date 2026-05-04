"""Module-level SSE broadcaster.

Subscribers get an asyncio.Queue; the addon calls ``emit()`` to push
events to all connected queues.

This module imports no internal Transport Matters modules.
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

QUEUE_MAX_SIZE = 1000

_subscribers: dict[int, asyncio.Queue[str]] = {}
_next_id: int = 0


def subscribe() -> asyncio.Queue[str]:
    global _next_id
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
    _next_id += 1
    _subscribers[_next_id] = q
    q._subscriber_id = _next_id  # type: ignore[attr-defined]
    return q


def unsubscribe(q: asyncio.Queue[str]) -> None:
    sid = getattr(q, "_subscriber_id", None)
    if sid is not None:
        _subscribers.pop(sid, None)


def emit(event: dict[str, object]) -> None:
    data = json.dumps(event, default=str)
    for sid, q in list(_subscribers.items()):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning(
                "Dropped SSE event for subscriber %d (queue full, maxsize=%d)",
                sid,
                QUEUE_MAX_SIZE,
            )
