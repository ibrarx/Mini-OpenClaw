"""
Event emitter for run status updates.

Provides an in-memory pub/sub mechanism so routes can poll for
state changes. Will be replaced with WebSocket in a stretch goal.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class EventEmitter:
    """Simple async event emitter for run lifecycle updates.

    Subscribers receive events through asyncio.Queue instances.
    This is suitable for the V1 polling model and can be upgraded
    to WebSocket push later.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Broadcast an event to all subscribers of the given type.

        Args:
            event_type: Event category (e.g. ``run_created``, ``step_completed``).
            data: Arbitrary payload dict.
        """
        payload = {"event_type": event_type, "data": data or {}}
        for queue in self._subscribers.get(event_type, []):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("Event queue full, dropping %s event", event_type)

    def subscribe(self, event_type: str) -> asyncio.Queue[dict[str, Any]]:
        """Create a queue that receives events of the given type.

        Returns:
            An asyncio.Queue that will receive event dicts.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers[event_type].append(queue)
        return queue

    def unsubscribe(self, event_type: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue."""
        subs = self._subscribers.get(event_type, [])
        if queue in subs:
            subs.remove(queue)
