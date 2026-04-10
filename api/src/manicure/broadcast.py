"""Module-level SSE broadcaster.

Subscribers get an asyncio.Queue; the addon calls ``emit()`` to push
events to all connected queues.

This module imports nothing from ``manicure``.
"""

import asyncio
import contextlib
import json

_subscribers: set[asyncio.Queue[str]] = set()


def subscribe() -> asyncio.Queue[str]:
    q: asyncio.Queue[str] = asyncio.Queue()
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue[str]) -> None:
    _subscribers.discard(q)


def emit(event: dict[str, object]) -> None:
    data = json.dumps(event, default=str)
    for q in list(_subscribers):
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(data)
