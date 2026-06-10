"""Terminal scrollback and attachment fanout for managed runs."""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

__all__ = [
    "DEFAULT_ATTACHMENT_QUEUE_SIZE",
    "DEFAULT_SCROLLBACK_BYTES",
    "SLOW_VIEWER_CLOSE_CODE",
    "AttachedTerminal",
    "AttachmentClosed",
    "PtyChunk",
    "ScrollbackRing",
    "TerminalAttachment",
    "TerminalFanout",
    "TerminalQueueItem",
]

DEFAULT_SCROLLBACK_BYTES = 2 * 1024 * 1024
DEFAULT_ATTACHMENT_QUEUE_SIZE = 256
SLOW_VIEWER_CLOSE_CODE = "retryable-overload"


@dataclass(frozen=True, slots=True)
class PtyChunk:
    seq: int
    data: bytes
    emitted_at: datetime


@dataclass(frozen=True, slots=True)
class AttachmentClosed:
    code: str
    retryable: bool
    message: str


TerminalQueueItem = PtyChunk | AttachmentClosed


class ScrollbackRing:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        max_bytes: int = DEFAULT_SCROLLBACK_BYTES,
    ) -> None:
        if max_bytes < 0:
            raise ValueError("scrollback max_bytes must be non negative")
        self._max_bytes = max_bytes
        self._clock = clock
        self._chunks: deque[PtyChunk] = deque()
        self._total_bytes = 0
        self._next_seq = 0
        self._truncated = False

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def next_seq(self) -> int:
        return self._next_seq

    @property
    def truncated(self) -> bool:
        return self._truncated

    def append(self, data: bytes, *, emitted_at: datetime | None = None) -> PtyChunk:
        emitted = emitted_at or self._clock()
        seq = self._next_seq
        self._next_seq += 1
        live_chunk = PtyChunk(seq=seq, data=data, emitted_at=emitted)
        if self._max_bytes == 0:
            if data:
                self._truncated = True
            return live_chunk

        if len(data) > self._max_bytes:
            self._truncated = True
            stored_data = data[-self._max_bytes :]
        else:
            stored_data = data
        if stored_data:
            stored_chunk = PtyChunk(seq=seq, data=stored_data, emitted_at=emitted)
            self._chunks.append(stored_chunk)
            self._total_bytes += len(stored_data)
            self._trim()
        return live_chunk

    def snapshot(self) -> tuple[PtyChunk, ...]:
        return tuple(self._chunks)

    def _trim(self) -> None:
        while self._total_bytes > self._max_bytes and self._chunks:
            chunk = self._chunks.popleft()
            self._total_bytes -= len(chunk.data)
            self._truncated = True


@dataclass(slots=True)
class TerminalAttachment:
    attachment_id: str
    queue: asyncio.Queue[TerminalQueueItem]
    cols: int
    rows: int
    connected_at: datetime
    closed_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AttachedTerminal:
    attachment: TerminalAttachment
    scrollback: tuple[PtyChunk, ...]
    start_seq: int


class TerminalFanout:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        scrollback_bytes: int = DEFAULT_SCROLLBACK_BYTES,
        attachment_queue_size: int = DEFAULT_ATTACHMENT_QUEUE_SIZE,
    ) -> None:
        self.scrollback = ScrollbackRing(max_bytes=scrollback_bytes, clock=clock)
        self.attachments: dict[str, TerminalAttachment] = {}
        self._clock = clock
        self._attachment_queue_size = attachment_queue_size

    def attach(
        self,
        *,
        cols: int,
        rows: int,
        attachment_id: str | None = None,
        queue_maxsize: int | None = None,
    ) -> AttachedTerminal:
        scrollback = self.scrollback.snapshot()
        start_seq = self.scrollback.next_seq
        attachment = TerminalAttachment(
            attachment_id=attachment_id or uuid4().hex,
            queue=asyncio.Queue(maxsize=queue_maxsize or self._attachment_queue_size),
            cols=cols,
            rows=rows,
            connected_at=self._clock(),
        )
        self.attachments[attachment.attachment_id] = attachment
        return AttachedTerminal(
            attachment=attachment,
            scrollback=scrollback,
            start_seq=start_seq,
        )

    def append(self, data: bytes, *, emitted_at: datetime) -> tuple[PtyChunk, tuple[str, ...]]:
        chunk = self.scrollback.append(data, emitted_at=emitted_at)
        overloaded: list[str] = []
        for attachment in tuple(self.attachments.values()):
            try:
                attachment.queue.put_nowait(chunk)
            except asyncio.QueueFull:
                overloaded.append(attachment.attachment_id)
        for attachment_id in overloaded:
            self.close_attachment(
                attachment_id,
                code=SLOW_VIEWER_CLOSE_CODE,
                retryable=True,
                message="terminal output queue overloaded; reconnect to resume",
            )
        return chunk, tuple(overloaded)

    def detach(self, attachment_id: str) -> bool:
        return self.attachments.pop(attachment_id, None) is not None

    def close_all(self, *, code: str, retryable: bool, message: str) -> None:
        for attachment_id in tuple(self.attachments):
            self.close_attachment(
                attachment_id,
                code=code,
                retryable=retryable,
                message=message,
            )

    def close_attachment(
        self,
        attachment_id: str,
        *,
        code: str,
        retryable: bool,
        message: str,
    ) -> bool:
        attachment = self.attachments.pop(attachment_id, None)
        if attachment is None:
            return False
        attachment.closed_reason = code
        close_item = AttachmentClosed(code=code, retryable=retryable, message=message)
        with contextlib.suppress(asyncio.QueueFull):
            attachment.queue.put_nowait(close_item)
        return True
