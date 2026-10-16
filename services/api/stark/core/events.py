"""In-process publish/subscribe bus. The dashboard receives these over SSE.

Events only ever describe things that actually happened in the backend; the
UI never animates work that isn't running.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any


class EventBus:
    def __init__(self, max_queue: int = 1000) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._max_queue = max_queue
        self.history: list[dict[str, Any]] = []  # small ring buffer for late subscribers

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._subscribers.discard(q)

    def publish(self, type_: str, data: dict[str, Any]) -> None:
        event = {"type": type_, "ts": datetime.now(timezone.utc).isoformat(), "data": data}
        self.history.append(event)
        del self.history[:-200]
        payload = json.dumps(event, default=str)
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:  # slow consumer: drop its oldest event, never block agents
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
