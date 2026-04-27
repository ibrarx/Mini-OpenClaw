"""
Conversation orchestrator — the runtime brain.

Owns the full run lifecycle: receive request → fetch context → plan →
validate → execute → collect outputs → update memory → return result.

Full pipeline wiring in T04/T05; this file provides the class interface
and a minimal stub that creates a run record.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from ..core.audit import AuditLogger
from ..core.events import EventEmitter
from ..core.executor import Executor
from ..core.planner import Planner
from ..core.policy import PolicyEngine
from ..models.run import Plan, Run, RunStatus

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates the full agent pipeline for a single run.

    Args:
        db: Active database connection.
        planner: Plan generator instance.
        policy: Policy engine instance.
        executor: Tool executor instance.
        audit: Audit logger instance.
        events: Event emitter instance.
    """

    def __init__(
        self,
        db: aiosqlite.Connection,
        planner: Planner,
        policy: PolicyEngine,
        executor: Executor,
        audit: AuditLogger,
        events: EventEmitter,
    ) -> None:
        self._db = db
        self._planner = planner
        self._policy = policy
        self._executor = executor
        self._audit = audit
        self._events = events

    async def process_message(
        self,
        message: str,
        session_id: str,
        workspace_id: str = "default",
    ) -> Run:
        """Process a user message through the full agent pipeline.

        Creates a run record, generates a plan, validates it,
        executes approved steps, and returns the completed run.

        Args:
            message: The user's natural-language input.
            session_id: Active session identifier.
            workspace_id: Logical workspace scope.

        Returns:
            The created Run object with plan and status.

        Raises:
            PlannerError: If Claude API fails after retries.
            PolicyError: If all proposed actions are forbidden.
        """
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        # Create DB record
        await self._db.execute(
            """
            INSERT INTO runs (id, session_id, workspace_id, status, user_message, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, session_id, workspace_id, RunStatus.PLANNING.value, message, now, now),
        )
        await self._db.commit()

        await self._audit.log_event(
            "run_created", run_id=run_id, details={"message": message}
        )
        await self._events.emit("run_created", {"run_id": run_id})

        # Stub: mark as completed with a placeholder response.
        # Real pipeline will be wired in T04.
        plan = await self._planner.create_plan(message)
        plan_json = plan.model_dump_json()

        final_response = (
            f"[Stub] Received your message: {message!r}. "
            "Full pipeline not yet connected."
        )

        await self._db.execute(
            """
            UPDATE runs SET status = ?, plan = ?, final_response = ?, updated_at = ?
            WHERE id = ?
            """,
            (RunStatus.COMPLETED.value, plan_json, final_response, now, run_id),
        )
        await self._db.commit()

        return Run(
            run_id=run_id,
            session_id=session_id,
            workspace_id=workspace_id,
            status=RunStatus.PLANNING,
            user_message=message,
            plan=plan,
            created_at=now,
            updated_at=now,
        )
