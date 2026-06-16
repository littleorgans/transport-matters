"""Run-scoped SSE broadcaster.

Subscribers get an asyncio.Queue; the addon calls ``emit()`` to push
events to connected queues for the same run.

This module imports no internal Transport Matters modules.
"""

import asyncio
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

QUEUE_MAX_SIZE = 1000


@dataclass(frozen=True)
class _Subscriber:
    run_id: str
    queue: asyncio.Queue[str]


_subscribers: dict[int, _Subscriber] = {}
_next_id: int = 0


def _required_run_id(run_id: object) -> str:
    if not isinstance(run_id, str) or run_id == "":
        raise ValueError("run_id is required")
    return run_id


def subscribe(run_id: str) -> asyncio.Queue[str]:
    global _next_id
    run_id = _required_run_id(run_id)
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
    _next_id += 1
    _subscribers[_next_id] = _Subscriber(run_id=run_id, queue=q)
    q._subscriber_id = _next_id  # type: ignore[attr-defined]
    return q


def unsubscribe(q: asyncio.Queue[str]) -> None:
    sid = getattr(q, "_subscriber_id", None)
    if sid is not None:
        _subscribers.pop(sid, None)


def emit(event: dict[str, object], *, run_id: str) -> None:
    run_id = _required_run_id(run_id)
    payload = dict(event)
    payload["run_id"] = run_id
    data = json.dumps(payload, default=str)
    for sid, subscriber in list(_subscribers.items()):
        if subscriber.run_id != run_id:
            continue
        try:
            subscriber.queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning(
                "Dropped SSE event for subscriber %d (queue full, maxsize=%d)",
                sid,
                QUEUE_MAX_SIZE,
            )
