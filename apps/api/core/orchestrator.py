"""
Conversation orchestrator — the runtime brain.

Owns the full run lifecycle: receive request -> fetch context -> plan ->
validate -> execute -> collect outputs -> update memory -> return result.
"""
from __future__ import annotations
import json, logging, uuid
from datetime import datetime, timezone
from typing import Any
import aiosqlite
from ..core.audit import AuditLogger
from ..core.events import EventEmitter
from ..core.executor import Executor
from ..core.planner import Planner, PlannerError
from ..core.policy import PolicyEngine
from ..memory.manager import MemoryManager
from ..memory.retrieval import MemoryRetrieval
from ..models.run import Plan, Run, RunStatus, TaskType
from ..models.step import RunStep, StepStatus

logger = logging.getLogger(__name__)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Orchestrator:
    """Coordinates the full agent pipeline for a single run."""

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
        self._runs: dict[str, Run] = {}

    async def process_message(
        self,
        message: str,
        session_id: str,
        workspace_id: str = "default",
    ) -> Run:
        """Process a user message through the full agent pipeline.

        Args:
            message: The user's natural language input.
            session_id: Active session identifier.
            workspace_id: Logical workspace scope.

        Returns:
            The created Run object with plan and status.
        """
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        now = _now()

        await self._db.execute(
            "INSERT INTO runs (id, session_id, workspace_id, status, user_message, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (run_id, session_id, workspace_id, RunStatus.PLANNING.value, message, now, now),
        )
        await self._db.commit()
        await self._audit.log_event("run_created", run_id=run_id, details={"message": message})
        await self._events.emit("run_created", {"run_id": run_id})

        # ── Fetch memory context ──
        memory_context = ""
        try:
            retrieval = MemoryRetrieval(self._db)
            memory_context = await retrieval.get_context_for_planner(
                message=message,
                workspace_id=workspace_id,
            )
        except Exception as exc:
            logger.warning("Memory retrieval failed: %s", exc)

        # ── Ask planner ──
        try:
            plan = await self._planner.create_plan(
                message=message,
                context={"memory_context": memory_context} if memory_context else None,
                available_tools=self._planner._registry.get_all_manifests() if self._planner._registry else None,
            )
        except PlannerError as exc:
            return await self._fail_run(run_id, session_id, workspace_id, message, str(exc), now)

        await self._audit.log_event("plan_ready", run_id=run_id, details={"task_type": plan.task_type.value, "num_steps": len(plan.steps)})

        # Direct answer — no tools needed
        if plan.task_type in (TaskType.DIRECT_ANSWER, TaskType.CLARIFICATION_NEEDED):
            run = await self._complete_run(run_id, session_id, workspace_id, message, plan, plan.reasoning, now)
            await self._store_episode(run, workspace_id)
            return run

        # ── Execute steps ──
        run = Run(run_id=run_id, session_id=session_id, workspace_id=workspace_id,
                  status=RunStatus.RUNNING, user_message=message, plan=plan, created_at=now, updated_at=now)
        self._runs[run_id] = run

        exec_context = {"workspace_root": str(self._policy.workspace_root), "db": self._db, "run_id": run_id, "session_id": session_id}
        all_results: list[dict] = []

        for step in plan.steps:
            step.run_id = run_id
            decision = self._policy.validate_step(step)
            await self._audit.log_event("policy_decision", run_id=run_id, step_id=step.step_id,
                details={"tool": step.tool, "allowed": decision.allowed, "classification": decision.classification, "reason": decision.reason})

            if not decision.allowed:
                step.status = StepStatus.SKIPPED
                step.error = decision.reason
                continue

            if decision.classification == "approval_required":
                step.status = StepStatus.AWAITING_APPROVAL
                await self._save_step(run_id, step, len(all_results))
                await self._save_approval_request(run_id, step)
                run.status = RunStatus.AWAITING_APPROVAL
                await self._update_run_db(run_id, run.status.value, plan, None, _now())
                self._runs[run_id] = run
                await self._events.emit("approval_requested", {"run_id": run_id, "step_id": step.step_id, "tool": step.tool})
                return run

            # Safe step — execute immediately
            result = await self._execute_step(step, exec_context, run_id)
            if result:
                all_results.append(result)

        final = self._build_final_response(all_results)
        run = await self._complete_run(run_id, session_id, workspace_id, message, plan, final, now)
        await self._store_episode(run, workspace_id)
        return run

    async def approve_step(self, run_id: str, step_id: str, approved: bool, db: aiosqlite.Connection | None = None) -> Run:
        """Process approval and resume execution.

        Args:
            run_id: The run to approve.
            step_id: The step to approve.
            approved: True to approve, False to reject.
            db: Fresh database connection (the original one from chat is closed).
        """
        run = self._runs.get(run_id)
        if not run or not run.plan:
            raise ValueError(f"Run not found or no plan: {run_id}")

        # Use the fresh db connection if provided
        if db is not None:
            self._db = db
            self._audit = AuditLogger(db)
            if self._executor._audit is not None:
                self._executor._audit = self._audit

        target = None
        for s in run.plan.steps:
            if s.step_id == step_id:
                target = s; break
        if not target or target.status != StepStatus.AWAITING_APPROVAL:
            raise ValueError(f"Step {step_id} not awaiting approval")

        await self._audit.log_event("approval_decision", run_id=run_id, step_id=step_id, details={"approved": approved})
        now = _now()
        await self._db.execute(
            "INSERT INTO approvals (id,run_id,step_id,payload,approved,decided_at,created_at) VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), run_id, step_id, json.dumps({"tool":target.tool,"args":target.args}), 1 if approved else 0, now, now))
        await self._db.commit()

        if not approved:
            target.status = StepStatus.SKIPPED
            run.status = RunStatus.CANCELLED
            run.final_response = f"Step {step_id} rejected by user."
            await self._update_run_db(run_id, run.status.value, run.plan, run.final_response, now)
            return run

        # Execute approved step and continue
        exec_context = {"workspace_root": str(self._policy.workspace_root), "db": self._db, "run_id": run_id, "session_id": run.session_id}
        all_results = self._collect_completed_results(run)
        result = await self._execute_step(target, exec_context, run_id)
        if result:
            all_results.append(result)

        # Continue remaining pending steps
        found = False
        for step in run.plan.steps:
            if step.step_id == step_id:
                found = True; continue
            if not found or step.status != StepStatus.PENDING:
                continue
            step.run_id = run_id
            decision = self._policy.validate_step(step)
            if not decision.allowed:
                step.status = StepStatus.SKIPPED; continue
            if decision.classification == "approval_required":
                step.status = StepStatus.AWAITING_APPROVAL
                await self._save_step(run_id, step, len(all_results))
                await self._save_approval_request(run_id, step)
                run.status = RunStatus.AWAITING_APPROVAL
                await self._update_run_db(run_id, run.status.value, run.plan, None, _now())
                return run
            r = await self._execute_step(step, exec_context, run_id)
            if r: all_results.append(r)

        run.status = RunStatus.COMPLETED
        run.final_response = self._build_final_response(all_results)
        await self._update_run_db(run_id, run.status.value, run.plan, run.final_response, _now())
        await self._store_episode(run, run.workspace_id)
        return run

    # ------------------------------------------------------------------
    # Memory integration
    # ------------------------------------------------------------------

    async def _store_episode(self, run: Run, workspace_id: str) -> None:
        """Store a completed run as an episodic memory item.

        Args:
            run: The completed run.
            workspace_id: Logical workspace scope.
        """
        if run.status not in (RunStatus.COMPLETED, RunStatus.FAILED):
            return

        try:
            manager = MemoryManager(self._db)
            # Build episode content
            tools_used = []
            if run.plan and run.plan.steps:
                tools_used = [s.tool for s in run.plan.steps if s.status == StepStatus.COMPLETED]

            content = f"User asked: {run.user_message}"
            if tools_used:
                content += f"\nTools used: {', '.join(tools_used)}"
            if run.final_response:
                # Truncate long responses for memory
                resp = run.final_response[:300]
                content += f"\nResult: {resp}"

            summary = f"{run.user_message[:100]}"
            if tools_used:
                summary += f" (used {', '.join(tools_used)})"

            await manager.store_episode(
                content=content,
                summary=summary,
                source=f"run:{run.run_id}",
                workspace_id=workspace_id,
                run_id=run.run_id,
            )
            await self._audit.log_event(
                "memory_written",
                run_id=run.run_id,
                details={"memory_type": "episode", "summary": summary[:200]},
            )
        except Exception as exc:
            logger.warning("Failed to store episode memory: %s", exc)

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    async def _execute_step(self, step: RunStep, context: dict, run_id: str) -> dict | None:
        step.status = StepStatus.RUNNING; step.started_at = _now()
        await self._events.emit("step_started", {"run_id": run_id, "step_id": step.step_id})
        result = await self._executor.execute_step(step, context)
        step.finished_at = _now()
        if result.status == "success":
            step.status = StepStatus.COMPLETED; step.result = result.output
            await self._events.emit("step_completed", {"run_id": run_id, "step_id": step.step_id})
            return {"step": step.step_id, "tool": step.tool, "output": result.output}
        else:
            step.status = StepStatus.FAILED; step.error = result.error
            await self._events.emit("step_failed", {"run_id": run_id, "step_id": step.step_id})
            return None

    def _collect_completed_results(self, run: Run) -> list[dict]:
        results = []
        if run.plan:
            for s in run.plan.steps:
                if s.status == StepStatus.COMPLETED and s.result:
                    results.append({"step": s.step_id, "tool": s.tool, "output": s.result})
        return results

    def _build_final_response(self, results: list[dict]) -> str:
        if not results:
            return "No results were produced."
        parts = []
        for r in results:
            tool = r.get("tool",""); output = r.get("output",{})
            if tool == "list_files":
                names = [e["name"] for e in output.get("entries",[])[:20]]
                parts.append(f"Files: {', '.join(names)}")
            elif tool == "read_file":
                parts.append(f"File content:\n{output.get('content','')[:1000]}")
            elif tool == "write_file":
                parts.append(f"File written: {output.get('path','')}")
            elif tool == "search_in_files":
                m = output.get("matches",[]); parts.append(f"Found {output.get('total_matches',0)} matches")
                for match in m[:5]: parts.append(f"  {match['file']}:{match['line_number']}: {match['line']}")
            elif tool == "run_shell_safe":
                parts.append(f"Command output:\n{output.get('stdout','')[:1000]}")
            elif tool == "remember_fact":
                parts.append(f"Remembered: {output.get('content','')}")
            elif tool == "search_memory":
                items = output.get("items",[]); parts.append(f"Found {len(items)} memory items")
            else:
                parts.append(f"{tool}: {json.dumps(output)[:200]}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    async def _fail_run(self, run_id, session_id, workspace_id, message, error, now) -> Run:
        await self._db.execute("UPDATE runs SET status=?, final_response=?, updated_at=? WHERE id=?",
            (RunStatus.FAILED.value, f"Planning failed: {error}", _now(), run_id))
        await self._db.commit()
        return Run(run_id=run_id, session_id=session_id, workspace_id=workspace_id, status=RunStatus.FAILED, user_message=message, final_response=f"Planning failed: {error}")

    async def _complete_run(self, run_id, session_id, workspace_id, message, plan, final, now) -> Run:
        await self._update_run_db(run_id, RunStatus.COMPLETED.value, plan, final, _now())
        run = Run(run_id=run_id, session_id=session_id, workspace_id=workspace_id, status=RunStatus.COMPLETED, user_message=message, plan=plan, final_response=final)
        self._runs[run_id] = run
        return run

    async def _update_run_db(self, run_id, status, plan, final, now) -> None:
        plan_json = plan.model_dump_json() if plan else None
        await self._db.execute("UPDATE runs SET status=?, plan=?, final_response=?, updated_at=? WHERE id=?",
            (status, plan_json, final, now, run_id))
        await self._db.commit()

    async def _save_step(self, run_id: str, step: RunStep, index: int) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO run_steps (id,run_id,step_index,tool,args,risk_level,status) VALUES (?,?,?,?,?,?,?)",
            (step.step_id, run_id, index, step.tool, json.dumps(step.args), step.risk_level.value if hasattr(step.risk_level,'value') else str(step.risk_level), step.status.value))
        await self._db.commit()

    async def _save_approval_request(self, run_id: str, step: RunStep) -> None:
        await self._db.execute(
            "INSERT INTO approvals (id,run_id,step_id,payload,created_at) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), run_id, step.step_id, json.dumps({"tool":step.tool,"args":step.args}), _now()))
        await self._db.commit()
