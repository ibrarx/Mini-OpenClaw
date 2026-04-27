"""
Append-only audit logger.

Logs every significant event in the agent pipeline: incoming messages,
planner decisions, policy evaluations, approvals, tool executions,
memory writes, and final responses. All entries are immutable once written.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class AuditLogger:
    """Append-only audit event writer backed by SQLite."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def log_event(
        self,
        event_type: str,
        run_id: str | None = None,
        step_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> str:
        """Write an audit event and return its id.

        Args:
            event_type: Category of event (e.g. ``plan_created``,
                ``policy_decision``, ``tool_executed``).
            run_id: Related run identifier, if applicable.
            step_id: Related step identifier, if applicable.
            details: Arbitrary JSON-serialisable payload.

        Returns:
            The generated event id.
        """
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO audit_events (id, event_type, run_id, step_id, data, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_type,
                run_id,
                step_id,
                json.dumps(details or {}),
                now,
            ),
        )
        await self._db.commit()
        logger.debug("Audit event %s: %s (run=%s)", event_id, event_type, run_id)
        return event_id

    async def get_events(
        self,
        run_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve audit events with optional filters.

        Args:
            run_id: Filter to events for a specific run.
            event_type: Filter to a specific event category.
            limit: Maximum number of events to return.

        Returns:
            List of event dicts ordered by creation time descending.
        """
        clauses: list[str] = []
        params: list[Any] = []

        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        rows = await self._db.execute_fetchall(
            f"SELECT * FROM audit_events {where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["data"] = json.loads(item.get("data", "{}"))
            results.append(item)
        return results
