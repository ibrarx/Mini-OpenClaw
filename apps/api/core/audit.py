"""
Append-only audit event logger.

Logs all significant events — policy decisions, tool executions,
approvals, memory writes — to the audit_events table.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class AuditLogger:
    """Append-only audit logger backed by SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def log_event(
        self,
        event_type: str,
        run_id: str | None = None,
        step_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> str:
        """
        Write an audit event to the database.

        Args:
            event_type: Category of event (policy_decision, tool_execution, etc.)
            run_id: Related run identifier, if any.
            step_id: Related step identifier, if any.
            details: Arbitrary JSON-serialisable event data.

        Returns:
            The generated event id.
        """
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        data = json.dumps(details or {}, default=str)

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_events (id, event_type, run_id, step_id, data, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (event_id, event_type, run_id, step_id, data, now),
                )
                await conn.commit()
            logger.debug("Audit event %s: %s", event_type, event_id)
        except Exception as exc:
            # Audit logging should never crash the caller
            logger.error("Failed to write audit event: %s", exc)

        return event_id
