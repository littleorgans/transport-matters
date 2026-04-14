"""SSE stream endpoint for live exchange updates."""

import asyncio
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from manicure import broadcast

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stream")
async def stream_exchanges() -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        q = broadcast.subscribe()
        try:
            yield 'data: {"type": "connected"}\n\n'
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {data}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
                except asyncio.CancelledError:
                    logger.debug("SSE client disconnected (cancelled)")
                    return
        except GeneratorExit:
            pass
        except Exception:
            logger.exception("Unexpected error in SSE generator")
        finally:
            broadcast.unsubscribe(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
