from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[str]]] = defaultdict(list)

    def subscribe(self, conversation_id: str) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue()
        self._subs[conversation_id].append(q)
        return q

    def unsubscribe(self, conversation_id: str, q: asyncio.Queue[str]) -> None:
        if conversation_id in self._subs:
            self._subs[conversation_id] = [x for x in self._subs[conversation_id] if x is not q]

    async def publish(self, conversation_id: str, event: str, data: dict[str, Any]) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
        for q in list(self._subs.get(conversation_id, [])):
            await q.put(payload)


bus = EventBus()
