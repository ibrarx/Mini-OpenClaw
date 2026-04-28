"""core/events — Simple event emitter for run status updates."""
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

class EventEmitter:
    def __init__(self) -> None:
        self._events: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def emit(self, run_id: str, event_type: str, data: dict[str, Any] | None = None) -> None:
        self._events[run_id].append({"event_type": event_type, "data": data or {}})

    def get_events(self, run_id: str) -> list[dict[str, Any]]:
        return list(self._events.get(run_id, []))

    def clear(self, run_id: str) -> None:
        self._events.pop(run_id, None)

event_emitter = EventEmitter()
