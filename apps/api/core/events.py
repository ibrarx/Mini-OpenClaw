"""core/events — Event emitter with asyncio pub/sub for SSE streaming.

Supports both the original list-based event storage (get_events/clear)
and real-time asyncio.Queue-based subscriptions for SSE consumers.
"""
import asyncio
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class EventEmitter:
    def __init__(self) -> None:
        # Original list-based storage (kept for backward compat)
        self._events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # SSE subscribers: run_id -> set of asyncio.Queue
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def emit(self, run_id: str, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Emit an event: store it and push to all SSE subscribers."""
        event = {"event_type": event_type, "data": data or {}}
        self._events[run_id].append(event)

        # Push to all active subscribers for this run_id
        for queue in self._subscribers.get(run_id, set()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("SSE queue full for run %s, dropping event %s", run_id, event_type)

    def get_events(self, run_id: str) -> list[dict[str, Any]]:
        return list(self._events.get(run_id, []))

    def clear(self, run_id: str) -> None:
        self._events.pop(run_id, None)

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Create a new subscription queue for the given run_id."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers[run_id].add(queue)
        logger.debug("SSE subscriber added for run %s (total: %d)", run_id, len(self._subscribers[run_id]))
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscription queue and clean up if no subscribers remain."""
        subs = self._subscribers.get(run_id)
        if subs:
            subs.discard(queue)
            if not subs:
                del self._subscribers[run_id]
        logger.debug("SSE subscriber removed for run %s", run_id)


event_emitter = EventEmitter()
