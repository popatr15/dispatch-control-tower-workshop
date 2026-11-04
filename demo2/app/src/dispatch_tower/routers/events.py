"""Server-sent events: route-state and decision changes pushed to every browser."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..deps import Ctx

router = APIRouter(tags=["events"])
HEARTBEAT_SECONDS = 15.0


@router.get("/events", include_in_schema=False)
async def events(request: Request, ctx: Ctx) -> StreamingResponse:
    queue = ctx.bus.subscribe()

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: change\ndata: {json.dumps(event, default=str)}\n\n"
        finally:
            ctx.bus.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
