"""
Conversation orchestrator — the runtime brain.

Owns the run lifecycle:
  receive request → fetch context → ask planner for plan →
  validate via policy → execute approved steps → collect outputs →
  update memory → return result.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from ..config import Settings
from ..core.audit import AuditLogger
from ..core.events import EventEmitter
from ..core.executor import Executor
from ..core.planner import Planner, PlannerError
from ..core.policy import PolicyEngine
from ..memory.manager import MemoryManager
from ..memory.retrieval import MemoryRetrieval
from ..models.run import Plan, Run, RunStatus, TaskType
from ..models.step import RunStep, StepStatus
from ..models.tool_manifest import ExecutionContext
from ..skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Orchestrator:
    """
    Central run lifecycle manager.

    Coordinates planner, policy, executor, memory, and audit
    to process user requests end-to-end.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_path = settings.resolved_database
        self.workspace_root = settings.resolved_workspace

        # Core components
        self.registry = SkillRegistry()
        self.policy = PolicyEngine(workspace_root=str(self.workspace_root), config=settings)
        self.audit = AuditLogger(self.db_path)
        self.events = EventEmitter()
        self.executor = Executor(self.registry, self.audit)
        self.planner = Planner(settings, self.registry)
        self.memory_manager = MemoryManager(self.db_path)
        self.memory_retrieval = MemoryRetrieval(self.db_path)

        # In-memory run store (V1 — will be persisted in T05+)
        self._runs: dict[str, Run] = {}

    async def process_message(
        self,
        message: str,
        session_id: str,
        workspace_id: str = "default",
    ) -> Run:
        """
        Process a user message through the full agent pipeline.

        Args:
            message: The user's natural language input.
            session_id: Active session identifier.
            workspace_id: Workspace scope.

        Returns:
            The created Run object with plan and status.

        Raises:
            PlannerError: If Claude API fails after retries.
        """
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        now = _now_iso()

        run = Run(
            run_id=run_id,
            session_id=session_id,
            workspace_id=workspace_id,
            status=RunStatus.PLANNING,
            user_message=message,
            created_at=now,
            updated_at=now,
        )
        self._runs[run_id] = run

        await self.audit.log_event(
            event_type="run_created",
            run_id=run_id,
            details={"message": message, "session_id": session_id},
        )
        await self.events.emit("run_created", run_id)

        # Persist to database
        await self._save_run(run)

        # 1. Fetch memory context
        memory_context = ""
        try:
            items = await self.memory_retrieval.search(
                query=message, workspace_id=workspace_id, limit=5,
            )
            if items:
                memory_context = "\n".join(
                    f"- [{item.memory_type.value}] {item.content}" for item in items
                )
        except Exception as exc:
            logger.warning("Memory retrieval failed: %s", exc)

        # 2. Ask planner for structured plan
        await self.events.emit("planning_started", run_id)
        try:
            plan = await self.planner.create_plan(
                user_message=message,
                memory_context=memory_context,
            )
        except PlannerError as exc:
            run.status = RunStatus.FAILED
            run.final_response = f"Planning failed: {exc}"
            run.updated_at = _now_iso()
            self._runs[run_id] = run
            await self._save_run(run)
            await self.events.emit("run_failed", run_id, data={"error": str(exc)})
            return run

        run.plan = plan
        run.updated_at = _now_iso()

        await self.audit.log_event(
            event_type="plan_ready",
            run_id=run_id,
            details={
                "task_type": plan.task_type.value,
                "confidence": plan.confidence,
                "num_steps": len(plan.steps),
            },
        )
        await self.events.emit("plan_ready", run_id, data={"task_type": plan.task_type.value})

        # 3. Handle direct answers (no tools needed)
        if plan.task_type == TaskType.DIRECT_ANSWER:
            run.status = RunStatus.COMPLETED
            run.final_response = plan.reasoning
            run.updated_at = _now_iso()
            self._runs[run_id] = run
            await self._save_run(run)
            await self.events.emit("run_completed", run_id)
            return run

        # 4. Handle clarification needed
        if plan.task_type == TaskType.CLARIFICATION_NEEDED:
            run.status = RunStatus.COMPLETED
            run.final_response = plan.reasoning
            run.updated_at = _now_iso()
            self._runs[run_id] = run
            await self._save_run(run)
            await self.events.emit("run_completed", run_id)
            return run

        # 5. Validate and execute steps
        run.status = RunStatus.RUNNING
        await self._execute_plan_steps(run)

        return run

    async def _execute_plan_steps(self, run: Run) -> None:
        """
        Validate and execute each step in the plan.

        Safe steps execute immediately. Risky steps pause for approval.
        """
        if not run.plan:
            return

        context = ExecutionContext(
            workspace_root=str(self.workspace_root),
            session_id=run.session_id,
            run_id=run.run_id,
            db_path=str(self.db_path),
        )

        all_results: list[dict[str, Any]] = []

        for step in run.plan.steps:
            # Policy check
            decision = self.policy.validate_step(step.tool, step.args)

            await self.audit.log_event(
                event_type="policy_decision",
                run_id=run.run_id,
                step_id=step.step_id,
                details={
                    "tool": step.tool,
                    "args": step.args,
                    "allowed": decision.allowed,
                    "requires_approval": decision.requires_approval,
                    "reason": decision.reason,
                },
            )

            step.risk_level = decision.risk_level

            if not decision.allowed:
                step.status = StepStatus.FORBIDDEN
                step.error = decision.reason
                await self.events.emit(
                    "step_failed", run.run_id, step.step_id,
                    data={"reason": decision.reason},
                )
                continue

            if decision.requires_approval:
                step.status = StepStatus.AWAITING_APPROVAL
                run.status = RunStatus.AWAITING_APPROVAL
                run.updated_at = _now_iso()
                self._runs[run.run_id] = run

                # Save approval request to database
                await self._save_approval(run.run_id, step)
                await self._save_run(run)
                await self.events.emit(
                    "approval_requested", run.run_id, step.step_id,
                    data={"tool": step.tool, "args": step.args},
                )
                # Stop executing — will resume when approval comes in
                return

            # Execute safe step immediately
            await self._execute_single_step(step, context, run, all_results)

        # All steps done
        run.status = RunStatus.COMPLETED
        run.final_response = self._build_final_response(run, all_results)
        run.updated_at = _now_iso()
        self._runs[run.run_id] = run
        await self._save_run(run)
        await self.events.emit("run_completed", run.run_id)

    async def _execute_single_step(
        self,
        step: RunStep,
        context: ExecutionContext,
        run: Run,
        all_results: list[dict[str, Any]],
    ) -> None:
        """Execute one step and update its status."""
        step.status = StepStatus.RUNNING
        step.started_at = _now_iso()
        await self.events.emit("step_started", run.run_id, step.step_id)

        result = await self.executor.execute_step(step, context, run.run_id)

        step.finished_at = _now_iso()
        if result.status == "success":
            step.status = StepStatus.COMPLETED
            step.result = result.output
            all_results.append({"step": step.step_id, "tool": step.tool, "output": result.output})
            await self.events.emit(
                "step_completed", run.run_id, step.step_id,
                data={"tool": step.tool},
            )
        else:
            step.status = StepStatus.FAILED
            step.error = result.error
            await self.events.emit(
                "step_failed", run.run_id, step.step_id,
                data={"error": result.error},
            )

        run.updated_at = _now_iso()
        self._runs[run.run_id] = run
        await self._save_run(run)

    async def approve_step(self, run_id: str, step_id: str, approved: bool) -> Run:
        """
        Process an approval decision and resume execution if approved.

        Args:
            run_id: The run containing the step.
            step_id: The step being approved/rejected.
            approved: True to approve, False to reject.

        Returns:
            The updated Run.
        """
        run = self._runs.get(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        if not run.plan:
            raise ValueError(f"Run has no plan: {run_id}")

        # Find the step
        target_step: RunStep | None = None
        for step in run.plan.steps:
            if step.step_id == step_id:
                target_step = step
                break

        if not target_step:
            raise ValueError(f"Step not found: {step_id}")

        if target_step.status != StepStatus.AWAITING_APPROVAL:
            raise ValueError(f"Step not awaiting approval: {step_id} (status={target_step.status})")

        await self.audit.log_event(
            event_type="approval_decision",
            run_id=run_id,
            step_id=step_id,
            details={"approved": approved, "tool": target_step.tool},
        )

        if not approved:
            target_step.status = StepStatus.CANCELLED
            run.status = RunStatus.CANCELLED
            run.final_response = f"Step {step_id} was rejected by user."
            run.updated_at = _now_iso()
            self._runs[run_id] = run
            await self._save_run(run)
            await self.events.emit("run_failed", run_id, data={"reason": "user_rejected"})
            return run

        # Approved — execute this step and continue
        target_step.status = StepStatus.APPROVED
        run.status = RunStatus.RUNNING
        run.updated_at = _now_iso()

        context = ExecutionContext(
            workspace_root=str(self.workspace_root),
            session_id=run.session_id,
            run_id=run.run_id,
            db_path=str(self.db_path),
        )

        all_results: list[dict[str, Any]] = []

        # Collect results from already-completed steps
        for s in run.plan.steps:
            if s.status == StepStatus.COMPLETED and s.result:
                all_results.append({"step": s.step_id, "tool": s.tool, "output": s.result})

        # Execute the approved step
        await self._execute_single_step(target_step, context, run, all_results)

        # Continue with remaining pending steps
        found_approved = False
        for step in run.plan.steps:
            if step.step_id == step_id:
                found_approved = True
                continue
            if not found_approved:
                continue
            if step.status != StepStatus.PENDING:
                continue

            # Policy check for next steps
            decision = self.policy.validate_step(step.tool, step.args)
            step.risk_level = decision.risk_level

            if not decision.allowed:
                step.status = StepStatus.FORBIDDEN
                step.error = decision.reason
                continue

            if decision.requires_approval:
                step.status = StepStatus.AWAITING_APPROVAL
                run.status = RunStatus.AWAITING_APPROVAL
                run.updated_at = _now_iso()
                self._runs[run.run_id] = run
                await self._save_approval(run.run_id, step)
                await self._save_run(run)
                await self.events.emit(
                    "approval_requested", run.run_id, step.step_id,
                    data={"tool": step.tool, "args": step.args},
                )
                return run

            await self._execute_single_step(step, context, run, all_results)

        # All steps done
        run.status = RunStatus.COMPLETED
        run.final_response = self._build_final_response(run, all_results)
        run.updated_at = _now_iso()
        self._runs[run_id] = run
        await self._save_run(run)
        await self.events.emit("run_completed", run_id)
        return run

    def get_run(self, run_id: str) -> Run | None:
        """Retrieve a run by ID."""
        return self._runs.get(run_id)

    def list_runs(
        self,
        session_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 20,
    ) -> list[Run]:
        """List runs with optional filters."""
        runs = list(self._runs.values())
        if session_id:
            runs = [r for r in runs if r.session_id == session_id]
        if workspace_id:
            runs = [r for r in runs if r.workspace_id == workspace_id]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    def _build_final_response(self, run: Run, results: list[dict[str, Any]]) -> str:
        """Build a human-friendly summary from step results."""
        if not results:
            return "No results were produced."

        parts: list[str] = []
        for r in results:
            tool = r.get("tool", "unknown")
            output = r.get("output", {})
            if tool == "list_files":
                entries = output.get("entries", [])
                names = [e["name"] for e in entries[:20]]
                parts.append(f"Files found: {', '.join(names)}")
            elif tool == "read_file":
                content = output.get("content", "")
                parts.append(f"File content:\n{content[:1000]}")
            elif tool == "write_file":
                path = output.get("path", "")
                parts.append(f"File written: {path}")
            elif tool == "search_in_files":
                matches = output.get("matches", [])
                total = output.get("total_matches", 0)
                parts.append(f"Found {total} matches")
                for m in matches[:5]:
                    parts.append(f"  {m['file']}:{m['line_number']}: {m['line']}")
            elif tool == "run_shell_safe":
                stdout = output.get("stdout", "")
                parts.append(f"Command output:\n{stdout[:1000]}")
            elif tool == "remember_fact":
                parts.append(f"Remembered: {output.get('content', '')}")
            elif tool == "search_memory":
                items = output.get("items", [])
                parts.append(f"Found {len(items)} memory items")
                for item in items[:5]:
                    parts.append(f"  - {item.get('content', '')}")
            else:
                parts.append(f"{tool}: {json.dumps(output)[:200]}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Database persistence
    # ------------------------------------------------------------------

    async def _save_run(self, run: Run) -> None:
        """Persist run state to the database."""
        try:
            plan_json = run.plan.model_dump_json() if run.plan else None
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO runs
                        (id, session_id, workspace_id, status, user_message,
                         plan, final_response, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id, run.session_id, run.workspace_id,
                        run.status.value, run.user_message,
                        plan_json, run.final_response,
                        run.created_at, run.updated_at,
                    ),
                )
                await conn.commit()
        except Exception as exc:
            logger.error("Failed to save run %s: %s", run.run_id, exc)

    async def _save_approval(self, run_id: str, step: RunStep) -> None:
        """Save an approval request to the database."""
        try:
            approval_id = f"appr_{uuid.uuid4().hex[:12]}"
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT INTO approvals (id, run_id, step_id, payload, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        approval_id, run_id, step.step_id,
                        json.dumps({"tool": step.tool, "args": step.args}),
                        _now_iso(),
                    ),
                )
                await conn.commit()
        except Exception as exc:
            logger.error("Failed to save approval: %s", exc)
