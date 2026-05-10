"""
core/orchestrator — The brain: run lifecycle manager.
"""
from __future__ import annotations
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from apps.api.config import Settings
from apps.api.core.audit import AuditLogger
from apps.api.core.events import event_emitter
from apps.api.core.executor import Executor
from apps.api.core.planner import Planner, PlannerError
from apps.api.core.policy import PolicyEngine
from apps.api.database import get_connection
from apps.api.memory.retrieval import MemoryRetrieval
from apps.api.models.run import (
    Plan, PlanStep, Run, RunStatus, StepStatus, RiskLevel, ToolResult,
)
from apps.api.skills.base import ToolContext
from apps.api.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, settings: Settings, registry: SkillRegistry) -> None:
        self._settings = settings
        self._registry = registry
        self._db_path = settings.resolved_database
        self._workspace = settings.resolved_workspace
        self._audit = AuditLogger(self._db_path)
        self._policy = PolicyEngine(self._workspace)
        self._executor = Executor(registry, self._audit)
        self._planner = Planner(
            anthropic_key=settings.anthropic_api_key,
            anthropic_model=settings.anthropic_model,
            gemini_key=settings.gemini_api_key,
            gemini_model=settings.gemini_model,
            registry=registry
        )

    async def handle_message(self, session_id: str, message: str,
                              workspace_id: str = "default") -> Run:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        run = Run(run_id=run_id, session_id=session_id, workspace_id=workspace_id,
                   status=RunStatus.PLANNING, user_message=message,
                   created_at=now, updated_at=now)
        await self._save_run(run)
        await self._store_message(session_id, "user", message, run_id)
        await self._audit.log("run_created", run_id=run_id,
                               data={"message": message, "session_id": session_id})
        event_emitter.emit(run_id, "run_created")
        task = asyncio.create_task(self._process_run(run))
        task.add_done_callback(self._task_done)
        return run

    @staticmethod
    def _task_done(task: asyncio.Task) -> None:
        """Log unhandled exceptions from background run tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Background run task failed: %s", exc, exc_info=exc)

    async def _process_run(self, run: Run) -> None:
        try:
            if not self._planner or not self._planner._provider:
                run.status = RunStatus.FAILED
                run.final_response = "No LLM provider configured. Set ANTHROPIC_API_KEY or GEMINI_API_KEY in .env"
                await self._save_run(run)
                return
            retrieval = MemoryRetrieval(self._db_path)
            memory_context = await retrieval.get_context_bundle(
                query=run.user_message, workspace_id=run.workspace_id)
            event_emitter.emit(run.run_id, "planning_started")
            plan_dict = await self._planner.create_plan(
                user_message=run.user_message, memory_context=memory_context,
                workspace_info=f"Workspace root: {self._workspace}")
            steps = []
            for i, sd in enumerate(plan_dict.get("steps", [])):
                raw_risk = sd.get("risk_level", "safe")
                try:
                    risk = RiskLevel(raw_risk)
                except ValueError:
                    risk = RiskLevel.SAFE
                steps.append(PlanStep(
                    step_id=sd.get("step_id", f"step_{i+1}"),
                    tool=sd.get("tool", ""), args=sd.get("args", {}),
                    risk_level=risk,
                    status=StepStatus.PENDING, reasoning=sd.get("reasoning")))
            run.plan = Plan(
                task_type=plan_dict.get("task_type", "direct_answer"),
                confidence=plan_dict.get("confidence", 0.5),
                reasoning=plan_dict.get("reasoning", ""),
                steps=steps, direct_response=plan_dict.get("direct_response"))
            await self._audit.log("plan_ready", run_id=run.run_id,
                                   data={"task_type": run.plan.task_type, "steps": len(steps)})
            event_emitter.emit(run.run_id, "plan_ready")
            if run.plan.task_type == "direct_answer":
                run.status = RunStatus.COMPLETED
                run.final_response = run.plan.direct_response
                await self._save_run(run)
                if run.final_response:
                    await self._store_message(run.session_id, "assistant", run.final_response, run.run_id)
                event_emitter.emit(run.run_id, "run_completed")
                return
            await self._execute_steps(run)
        except PlannerError as exc:
            run.status = RunStatus.FAILED
            run.final_response = f"Planning failed: {exc}"
            await self._save_run(run)
            event_emitter.emit(run.run_id, "run_failed")
        except Exception as exc:
            logger.error("Run %s failed: %s", run.run_id, exc, exc_info=True)
            run.status = RunStatus.FAILED
            run.final_response = f"Internal error: {exc}"
            await self._save_run(run)
            event_emitter.emit(run.run_id, "run_failed")

    async def _execute_steps(self, run: Run) -> None:
        assert run.plan is not None
        tool_results: list[dict[str, Any]] = []
        for step in run.plan.steps:
            tool = self._registry.get(step.tool)
            if tool is None:
                step.status = StepStatus.FAILED
                step.result = ToolResult(tool_name=step.tool, status="error",
                                          input=step.args, error=f"Unknown tool: {step.tool}")
                await self._save_run(run)
                continue
            manifest = tool.manifest()
            policy = self._policy.classify_tool(step.tool, manifest.risk_level.value,
                                                 manifest.approval_required)
            if step.tool in ("read_file", "write_file", "list_files", "search_in_files"):
                pc = self._policy.validate_path(step.args.get("path", "."),
                                                 write=(step.tool == "write_file"))
                if not pc.allowed:
                    step.status = StepStatus.FAILED
                    step.result = ToolResult(tool_name=step.tool, status="error",
                                              input=step.args, error=pc.reason)
                    await self._save_run(run)
                    continue
            if step.tool == "run_shell_safe":
                sc = self._policy.validate_shell(step.args.get("command", ""),
                                                  step.args.get("args", []))
                if not sc.allowed:
                    step.status = StepStatus.FAILED
                    step.result = ToolResult(tool_name=step.tool, status="error",
                                              input=step.args, error=sc.reason)
                    await self._save_run(run)
                    continue
            if policy.classification == "approval_required":
                step.status = StepStatus.AWAITING_APPROVAL
                run.status = RunStatus.AWAITING_APPROVAL
                await self._save_run(run)
                await self._audit.log("approval_requested", run_id=run.run_id,
                                       step_id=step.step_id, data={"tool": step.tool})
                event_emitter.emit(run.run_id, "approval_requested")
                approved = await self._wait_for_approval(run.run_id, step.step_id)
                logger.info("Run %s step %s: approval=%s", run.run_id, step.step_id, approved)
                if not approved:
                    step.status = StepStatus.FAILED
                    step.result = ToolResult(tool_name=step.tool, status="error",
                                              input=step.args, error="User rejected this action")
                    run.status = RunStatus.CANCELLED
                    run.final_response = "Run cancelled: user rejected an action."
                    await self._save_run(run)
                    event_emitter.emit(run.run_id, "run_failed")
                    return
            step.status = StepStatus.RUNNING
            run.status = RunStatus.RUNNING
            await self._save_run(run)
            context = ToolContext(workspace_root=str(self._workspace), run_id=run.run_id,
                                   step_id=step.step_id, db_path=str(self._db_path))
            result = await self._executor.execute_tool(step.tool, step.args, context)
            logger.info("Run %s step %s: tool=%s status=%s", run.run_id, step.step_id, step.tool, result.status)
            step.result = result
            step.status = StepStatus.COMPLETED if result.status == "success" else StepStatus.FAILED
            await self._save_run(run)
            tool_results.append({"tool": step.tool, "status": result.status,
                                  "output": result.output, "error": result.error})
        try:
            if self._planner and tool_results:
                logger.info("Run %s: generating summary...", run.run_id)
                run.final_response = await asyncio.wait_for(
                    self._planner.generate_summary(run.user_message, tool_results),
                    timeout=30.0,
                )
                logger.info("Run %s: summary generated", run.run_id)
            else:
                run.final_response = "Task completed."
        except asyncio.TimeoutError:
            logger.warning("Run %s: summary timed out after 30s", run.run_id)
            run.final_response = "Task completed. (Summary generation timed out.)"
        except Exception as exc:
            logger.warning("Run %s: summary failed: %s", run.run_id, exc)
            run.final_response = "Task completed. Check tool traces for details."
        all_ok = all(s.status == StepStatus.COMPLETED for s in run.plan.steps)
        run.status = RunStatus.COMPLETED if all_ok else RunStatus.FAILED
        logger.info("Run %s: final status=%s", run.run_id, run.status.value)
        await self._save_run(run)
        if run.final_response:
            await self._store_message(run.session_id, "assistant", run.final_response, run.run_id)
        event_emitter.emit(run.run_id, "run_completed")

    async def _wait_for_approval(self, run_id: str, step_id: str, timeout: float = 300) -> bool:
        start = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start) < timeout:
            try:
                conn = await get_connection(self._db_path)
                try:
                    rows = await conn.execute_fetchall(
                        "SELECT approved FROM approvals WHERE run_id=? AND step_id=? AND approved IS NOT NULL",
                        (run_id, step_id))
                    if rows:
                        return bool(rows[0]["approved"])
                finally:
                    await conn.close()
            except Exception as exc:
                logger.warning("Approval poll error (will retry): %s", exc)
            await asyncio.sleep(1.0)
        return False

    async def approve_step(self, run_id: str, step_id: str, approved: bool) -> Run | None:
        now = datetime.now(timezone.utc).isoformat()
        conn = await get_connection(self._db_path)
        try:
            existing = await conn.execute_fetchall(
                "SELECT id FROM approvals WHERE run_id=? AND step_id=?", (run_id, step_id))
            if existing:
                await conn.execute(
                    "UPDATE approvals SET approved=?, decided_at=? WHERE run_id=? AND step_id=?",
                    (1 if approved else 0, now, run_id, step_id))
            else:
                appr_id = f"appr_{uuid.uuid4().hex[:12]}"
                await conn.execute(
                    "INSERT INTO approvals (id,run_id,step_id,payload,approved,decided_at,created_at) VALUES (?,?,?,?,?,?,?)",
                    (appr_id, run_id, step_id, "{}", 1 if approved else 0, now, now))
            await conn.commit()
        finally:
            await conn.close()
        await self._audit.log("approval_decided", run_id=run_id, step_id=step_id,
                               data={"approved": approved})
        logger.info("Approval for run %s step %s: approved=%s", run_id, step_id, approved)

        # Resume execution if approved — handles case where background task
        # died (e.g. uvicorn --reload) and nobody is polling the approvals table.
        if approved:
            run = await self.get_run(run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                logger.info("Resuming execution for run %s after approval", run_id)
                task = asyncio.create_task(self._resume_after_approval(run, step_id))
                task.add_done_callback(self._task_done)

        return await self.get_run(run_id)

    async def _resume_after_approval(self, run: Run, approved_step_id: str) -> None:
        """Resume a run after approval, executing the approved step and any remaining steps.

        This handles the case where the original background task died (e.g. due
        to uvicorn --reload) and the _wait_for_approval loop is no longer running.
        """
        try:
            if not run.plan:
                return
            # Find the approved step and remaining steps
            tool_results: list[dict[str, Any]] = []
            found_approved = False
            for step in run.plan.steps:
                if step.step_id == approved_step_id:
                    found_approved = True
                if not found_approved:
                    # Already completed steps — collect their results
                    if step.result and step.result.status == "success":
                        tool_results.append({"tool": step.tool, "status": step.result.status,
                                              "output": step.result.output, "error": step.result.error})
                    continue
                if step.status in (StepStatus.COMPLETED, StepStatus.FAILED):
                    continue
                # Execute this step
                tool = self._registry.get(step.tool)
                if tool is None:
                    step.status = StepStatus.FAILED
                    step.result = ToolResult(tool_name=step.tool, status="error",
                                              input=step.args, error=f"Unknown tool: {step.tool}")
                    await self._save_run(run)
                    continue
                step.status = StepStatus.RUNNING
                run.status = RunStatus.RUNNING
                await self._save_run(run)
                context = ToolContext(workspace_root=str(self._workspace), run_id=run.run_id,
                                       step_id=step.step_id, db_path=str(self._db_path))
                result = await self._executor.execute_tool(step.tool, step.args, context)
                logger.info("Resume run %s step %s: tool=%s status=%s",
                             run.run_id, step.step_id, step.tool, result.status)
                step.result = result
                step.status = StepStatus.COMPLETED if result.status == "success" else StepStatus.FAILED
                await self._save_run(run)
                tool_results.append({"tool": step.tool, "status": result.status,
                                      "output": result.output, "error": result.error})

            # Generate summary
            try:
                if self._planner and tool_results:
                    run.final_response = await asyncio.wait_for(
                        self._planner.generate_summary(run.user_message, tool_results),
                        timeout=30.0,
                    )
                else:
                    run.final_response = "Task completed."
            except asyncio.TimeoutError:
                run.final_response = "Task completed. (Summary generation timed out.)"
            except Exception:
                run.final_response = "Task completed. Check tool traces for details."

            all_ok = all(s.status == StepStatus.COMPLETED for s in run.plan.steps)
            run.status = RunStatus.COMPLETED if all_ok else RunStatus.FAILED
            logger.info("Resume run %s: final status=%s", run.run_id, run.status.value)
            await self._save_run(run)
            if run.final_response:
                await self._store_message(run.session_id, "assistant", run.final_response, run.run_id)
            event_emitter.emit(run.run_id, "run_completed")
        except Exception as exc:
            logger.error("Resume run %s failed: %s", run.run_id, exc, exc_info=True)
            run.status = RunStatus.FAILED
            run.final_response = f"Internal error: {exc}"
            await self._save_run(run)
            event_emitter.emit(run.run_id, "run_failed")

    async def _save_run(self, run: Run) -> None:
        run.updated_at = datetime.now(timezone.utc).isoformat()
        plan_json = run.plan.model_dump_json() if run.plan else None
        conn = await get_connection(self._db_path)
        try:
            existing = await conn.execute_fetchall("SELECT id FROM runs WHERE id=?", (run.run_id,))
            if existing:
                await conn.execute(
                    "UPDATE runs SET status=?, plan=?, final_response=?, updated_at=? WHERE id=?",
                    (run.status.value, plan_json, run.final_response, run.updated_at, run.run_id))
            else:
                await conn.execute(
                    "INSERT INTO runs (id,session_id,workspace_id,status,user_message,plan,final_response,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (run.run_id, run.session_id, run.workspace_id, run.status.value,
                     run.user_message, plan_json, run.final_response, run.created_at, run.updated_at))
            await conn.commit()
        finally:
            await conn.close()

    async def get_run(self, run_id: str) -> Run | None:
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall("SELECT * FROM runs WHERE id=?", (run_id,))
            if not rows:
                return None
            return self._row_to_run(rows[0])
        finally:
            await conn.close()

    async def list_runs(self, session_id: str | None = None, workspace_id: str | None = None,
                         status: str | None = None, limit: int = 50, offset: int = 0) -> list[Run]:
        conditions, params = [], []
        if session_id:
            conditions.append("session_id=?"); params.append(session_id)
        if workspace_id:
            conditions.append("workspace_id=?"); params.append(workspace_id)
        if status:
            conditions.append("status=?"); params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", tuple(params))
            return [self._row_to_run(r) for r in rows]
        finally:
            await conn.close()

    async def cancel_run(self, run_id: str) -> Run | None:
        run = await self.get_run(run_id)
        if run is None:
            return None
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            return run
        run.status = RunStatus.CANCELLED
        run.final_response = "Run cancelled by user."
        await self._save_run(run)
        if run.plan:
            for step in run.plan.steps:
                if step.status == StepStatus.AWAITING_APPROVAL:
                    await self.approve_step(run_id, step.step_id, approved=False)
        event_emitter.emit(run_id, "run_cancelled")
        return run

    async def _store_message(self, session_id: str, role: str, content: str,
                              run_id: str | None = None) -> None:
        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        conn = await get_connection(self._db_path)
        try:
            existing = await conn.execute_fetchall("SELECT id FROM sessions WHERE id=?", (session_id,))
            if not existing:
                await conn.execute("INSERT INTO sessions (id,created_at,updated_at) VALUES (?,?,?)",
                                    (session_id, now, now))
            await conn.execute(
                "INSERT INTO messages (id,session_id,role,content,created_at,run_id) VALUES (?,?,?,?,?,?)",
                (msg_id, session_id, role, content, now, run_id))
            await conn.commit()
        finally:
            await conn.close()

    @staticmethod
    def _row_to_run(row: aiosqlite.Row) -> Run:
        plan = None
        if row["plan"]:
            try:
                plan = Plan.model_validate_json(row["plan"])
            except Exception:
                pass
        return Run(run_id=row["id"], session_id=row["session_id"], workspace_id=row["workspace_id"],
                    status=RunStatus(row["status"]), user_message=row["user_message"],
                    plan=plan, final_response=row["final_response"],
                    created_at=row["created_at"], updated_at=row["updated_at"])
