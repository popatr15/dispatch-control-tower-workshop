"""In-process fan-out of change events to SSE subscribers.

Producers may run on any thread (request handlers, the Postgres LISTEN thread);
each subscriber owns an asyncio queue bound to its event loop.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

Event = dict[str, Any]


class EventBus:
    def __init__(self, max_queue: int = 1000) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[Event]]] = []
        self._max_queue = max_queue

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue)
        with self._lock:
            self._subscribers.append((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        with self._lock:
            self._subscribers = [(lp, q) for lp, q in self._subscribers if q is not queue]

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, event: Event) -> None:
        with self._lock:
            targets = list(self._subscribers)
        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(_offer, queue, event)
            except RuntimeError:  # loop closed: subscriber is gone
                self.unsubscribe(queue)


def _offer(queue: asyncio.Queue[Event], event: Event) -> None:
    if queue.full():  # slow consumer: drop the oldest event, clients re-fetch on reconnect
        queue.get_nowait()
    queue.put_nowait(event)
