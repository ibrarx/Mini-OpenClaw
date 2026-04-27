"""
Event emitter — run status updates for polling/streaming.

V1 uses in-memory storage; the frontend polls GET /api/runs/{id}.
Events are also logged to the audit trail.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RunEvent(BaseModel):
    """A single run lifecycle event."""

    event_type: str
    run_id: str
    step_id: str | None = None
    data: dict[str, Any] = {}
    timestamp: str = ""


class EventEmitter:
    """
    In-memory event store for V1.

    Consumers poll for events by run_id. Each run keeps an ordered
    list of events. This will be upgraded to SSE/WebSocket in V2.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[RunEvent]] = defaultdict(list)

    async def emit(
        self,
        event_type: str,
        run_id: str,
        step_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> RunEvent:
        """
        Record and broadcast an event.

        Args:
            event_type: One of the defined event types.
            run_id: The run this event belongs to.
            step_id: Optional step reference.
            data: Arbitrary event payload.

        Returns:
            The created RunEvent.
        """
        event = RunEvent(
            event_type=event_type,
            run_id=run_id,
            step_id=step_id,
            data=data or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._events[run_id].append(event)
        logger.debug("Event %s for run %s", event_type, run_id)
        return event

    def get_events(self, run_id: str, after: int = 0) -> list[RunEvent]:
        """Return events for a run, optionally after an index."""
        return self._events.get(run_id, [])[after:]

    def clear(self, run_id: str) -> None:
        """Remove all events for a run."""
        self._events.pop(run_id, None)
