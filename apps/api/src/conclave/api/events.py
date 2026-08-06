from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from conclave.services.events import bus

router = APIRouter(tags=["events"])


@router.get("/conversations/{conversation_id}/events")
async def conversation_events(conversation_id: str, request: Request):
    queue = bus.subscribe(conversation_id)

    async def gen():
        try:
            yield "event: ready\ndata: {\"ok\": true}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield item
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            bus.unsubscribe(conversation_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")
