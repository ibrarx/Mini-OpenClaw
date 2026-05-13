"""
core/orchestrator — The brain: run lifecycle manager.

Supports two execution modes:
  - ReAct loop (default, ``settings.use_react=True``): iterative think→act→observe
  - Plan-and-execute (legacy, ``settings.use_react=False``): full upfront plan
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
    Observation, Plan, PlanStep, Run, RunStatus, StepStatus, RiskLevel, ToolResult,
)
from apps.api.providers import build_provider
from apps.api.providers.errors import ProviderConfigError
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
        try:
            provider = build_provider(settings)
            self._planner = Planner(provider, registry)
        except ProviderConfigError as exc:
            logger.warning("LLM provider not configured: %s", exc)
            self._planner = None

    async def handle_message(self, session_id: str, message: str,
                              workspace_id: str = "default") -> Run:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        run = Run(run_id=run_id, session_id=session_id, workspace_id=workspace_id,
                   status=RunStatus.PLANNING, user_message=message,
                   created_at=now, updated_at=now,
                   max_iterations=self._settings.react_max_iterations)
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
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Background run task failed: %s", exc, exc_info=exc)

    async def _process_run(self, run: Run) -> None:
        try:
            if not self._planner:
                run.status = RunStatus.FAILED
                run.final_response = (
                    "LLM provider not configured. Set ANTHROPIC_API_KEY or "
                    "GEMINI_API_KEY in .env (and optionally LLM_PROVIDER)."
                )
                await self._save_run(run)
                return

            if self._settings.use_react:
                await self._react_loop(run)
            else:
                await self._plan_and_execute(run)

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

    # ------------------------------------------------------------------
    # ReAct loop
    # ------------------------------------------------------------------

    async def _react_loop(self, run: Run) -> None:
        """Iterative ReAct loop: think → act → observe, up to max_iterations."""
        retrieval = MemoryRetrieval(self._db_path)
        memory_context = await retrieval.get_context_bundle(
            query=run.user_message, workspace_id=run.workspace_id)
        workspace_info = f"Workspace root: {self._workspace}"

        # Ensure plan exists for step tracking
        if run.plan is None:
            run.plan = Plan(task_type="react", reasoning="ReAct loop")

        while run.iterations < run.max_iterations:
            run.iterations += 1
            run.status = RunStatus.REACTING
            await self._save_run(run)

            # Build observation history for the planner
            obs_for_planner = [
                {
                    "tool": o.tool,
                    "status": o.result.status if o.result else "N/A",
                    "output": o.result.output if o.result and o.result.status == "success" else None,
                    "error": o.result.error if o.result and o.result.status != "success" else None,
                }
                for o in run.observations
                if o.tool is not None  # skip final_answer observations
            ]

            # THINK: ask planner for next action
            try:
                decision = await self._planner.react_step(
                    user_message=run.user_message,
                    observations=obs_for_planner,
                    memory_context=memory_context,
                    workspace_info=workspace_info,
                )
            except PlannerError:
                raise  # let _process_run handle it
            except Exception as exc:
                logger.error("ReAct planner error at iteration %d: %s", run.iterations, exc, exc_info=True)
                # Generate summary of partial results
                run.final_response = await self._summarize_partial(run)
                run.final_response += f"\n\n(Stopped: planner error at iteration {run.iterations})"
                run.status = RunStatus.FAILED
                await self._save_run(run)
                event_emitter.emit(run.run_id, "run_failed")
                return

            action = decision.get("action")
            step_id = f"step_{run.iterations}"
            now = datetime.now(timezone.utc).isoformat()

            # FINAL ANSWER
            if action == "final_answer":
                obs = Observation(
                    step_id=step_id, iteration=run.iterations,
                    reasoning=decision.get("reasoning", ""),
                    timestamp=now,
                )
                run.observations.append(obs)
                run.final_response = decision.get("response", "Task completed.")
                run.status = RunStatus.COMPLETED
                await self._save_run(run)
                if run.final_response:
                    await self._store_message(run.session_id, "assistant", run.final_response, run.run_id)
                await self._audit.log("run_completed", run_id=run.run_id,
                                       data={"iterations": run.iterations})
                event_emitter.emit(run.run_id, "run_completed")
                return

            # TOOL ACTION
            tool_name = decision.get("tool", "")
            tool_args = decision.get("args", {})
            reasoning = decision.get("reasoning", "")

            # Look up tool
            tool = self._registry.get(tool_name)
            if tool is None:
                error_result = ToolResult(
                    tool_name=tool_name, status="error", input=tool_args,
                    error=f"Unknown tool: {tool_name}",
                )
                obs = Observation(
                    step_id=step_id, iteration=run.iterations,
                    tool=tool_name, args=tool_args, reasoning=reasoning,
                    result=error_result, timestamp=now,
                )
                run.observations.append(obs)
                await self._save_run(run)
                await self._audit.log("react_iteration", run_id=run.run_id,
                                       step_id=step_id,
                                       data={"tool": tool_name, "status": "error",
                                             "error": "unknown tool"})
                continue

            manifest = tool.manifest()

            # POLICY CHECK
            policy_result = self._policy.classify_tool(
                tool_name, manifest.risk_level.value, manifest.approval_required)

            # Path validation for file tools
            if tool_name in ("read_file", "write_file", "list_files", "search_in_files"):
                pc = self._policy.validate_path(
                    tool_args.get("path", "."),
                    write=(tool_name == "write_file"))
                if not pc.allowed:
                    denied_result = ToolResult(
                        tool_name=tool_name, status="denied", input=tool_args,
                        error=f"policy: {pc.reason}",
                    )
                    obs = Observation(
                        step_id=step_id, iteration=run.iterations,
                        tool=tool_name, args=tool_args, reasoning=reasoning,
                        result=denied_result, timestamp=now,
                    )
                    run.observations.append(obs)
                    await self._save_run(run)
                    await self._audit.log("react_policy_denied", run_id=run.run_id,
                                           step_id=step_id,
                                           data={"tool": tool_name, "reason": pc.reason})
                    continue

            # Shell validation
            if tool_name == "run_shell_safe":
                sc = self._policy.validate_shell(
                    tool_args.get("command", ""), tool_args.get("args", []))
                if not sc.allowed:
                    denied_result = ToolResult(
                        tool_name=tool_name, status="denied", input=tool_args,
                        error=f"policy: {sc.reason}",
                    )
                    obs = Observation(
                        step_id=step_id, iteration=run.iterations,
                        tool=tool_name, args=tool_args, reasoning=reasoning,
                        result=denied_result, timestamp=now,
                    )
                    run.observations.append(obs)
                    await self._save_run(run)
                    await self._audit.log("react_policy_denied", run_id=run.run_id,
                                           step_id=step_id,
                                           data={"tool": tool_name, "reason": sc.reason})
                    continue

            # APPROVAL CHECK
            if policy_result.classification == "approval_required":
                # Create a PlanStep for the UI and pause
                plan_step = PlanStep(
                    step_id=step_id, tool=tool_name, args=tool_args,
                    risk_level=manifest.risk_level,
                    status=StepStatus.AWAITING_APPROVAL, reasoning=reasoning,
                )
                run.plan.steps.append(plan_step)
                run.status = RunStatus.AWAITING_APPROVAL
                # Store the pending observation (no result yet)
                pending_obs = Observation(
                    step_id=step_id, iteration=run.iterations,
                    tool=tool_name, args=tool_args, reasoning=reasoning,
                    timestamp=now,
                )
                run.observations.append(pending_obs)
                await self._save_run(run)
                await self._audit.log("approval_requested", run_id=run.run_id,
                                       step_id=step_id, data={"tool": tool_name})
                event_emitter.emit(run.run_id, "approval_requested")

                # Wait for user decision
                approved = await self._wait_for_approval(run.run_id, step_id)
                logger.info("Run %s step %s: approval=%s", run.run_id, step_id, approved)

                if not approved:
                    rejected_result = ToolResult(
                        tool_name=tool_name, status="rejected", input=tool_args,
                        error="user declined",
                    )
                    # Update the pending observation with rejection
                    run.observations[-1].result = rejected_result
                    plan_step.status = StepStatus.FAILED
                    plan_step.result = rejected_result
                    await self._save_run(run)
                    await self._audit.log("react_user_rejected", run_id=run.run_id,
                                           step_id=step_id, data={"tool": tool_name})

                    # Saga compensation: undo previously completed mutating steps.
                    # Without this, the LLM would try to "help" by calling write_file
                    # with empty content, which is worse than a proper rollback.
                    compensated = await self._compensate_completed_steps(run)

                    # End the run — don't let the LLM improvise undo actions.
                    comp_msg = ""
                    if compensated:
                        comp_names = [c.tool_name for c in compensated if c.status == "success"]
                        if comp_names:
                            comp_msg = (
                                f" Rolled back {len(comp_names)} previous "
                                f"step{'s' if len(comp_names) != 1 else ''}: "
                                f"{', '.join(comp_names)}."
                            )
                    run.final_response = (
                        f"Run stopped: you declined the {tool_name} action "
                        f"(step {run.iterations}).{comp_msg}"
                    )
                    run.status = RunStatus.CANCELLED
                    await self._save_run(run)
                    if run.final_response:
                        await self._store_message(
                            run.session_id, "assistant", run.final_response, run.run_id)
                    await self._audit.log("run_cancelled", run_id=run.run_id,
                                           data={"reason": "user_rejected",
                                                 "compensated": len(compensated)})
                    event_emitter.emit(run.run_id, "run_cancelled")
                    return

                # Approved — fall through to execution
                plan_step.status = StepStatus.RUNNING
                run.status = RunStatus.REACTING
                await self._save_run(run)
            else:
                # Auto-execute — create a PlanStep for the UI
                plan_step = PlanStep(
                    step_id=step_id, tool=tool_name, args=tool_args,
                    risk_level=manifest.risk_level,
                    status=StepStatus.RUNNING, reasoning=reasoning,
                )
                run.plan.steps.append(plan_step)
                await self._save_run(run)

            # ACT: execute the tool
            context = ToolContext(
                workspace_root=str(self._workspace), run_id=run.run_id,
                step_id=step_id, db_path=str(self._db_path),
            )
            result = await self._executor.execute_tool(tool_name, tool_args, context)

            # OBSERVE: record result
            plan_step.result = result
            plan_step.status = (
                StepStatus.COMPLETED if result.status == "success" else StepStatus.FAILED
            )

            # Update or create observation
            if (run.observations and run.observations[-1].step_id == step_id
                    and run.observations[-1].result is None):
                # Update pending observation from approval flow
                run.observations[-1].result = result
            else:
                obs = Observation(
                    step_id=step_id, iteration=run.iterations,
                    tool=tool_name, args=tool_args, reasoning=reasoning,
                    result=result, timestamp=datetime.now(timezone.utc).isoformat(),
                )
                run.observations.append(obs)

            await self._save_run(run)
            await self._audit.log("react_iteration", run_id=run.run_id,
                                   step_id=step_id,
                                   data={"tool": tool_name, "status": result.status,
                                         "iteration": run.iterations})
            event_emitter.emit(run.run_id, "step_completed")

        # Max iterations reached
        logger.warning("Run %s: max iterations (%d) reached", run.run_id, run.max_iterations)
        run.final_response = await self._summarize_partial(run)
        run.final_response += "\n\n(Stopped: maximum iterations reached)"
        run.status = RunStatus.FAILED
        await self._save_run(run)
        if run.final_response:
            await self._store_message(run.session_id, "assistant", run.final_response, run.run_id)
        await self._audit.log("run_failed", run_id=run.run_id,
                               data={"reason": "max_iterations_exceeded",
                                     "iterations": run.iterations})
        event_emitter.emit(run.run_id, "run_failed")

    async def _summarize_partial(self, run: Run) -> str:
        """Generate a summary from whatever observations we have so far."""
        tool_results = []
        for obs in run.observations:
            if obs.result and obs.tool:
                tool_results.append({
                    "tool": obs.tool, "status": obs.result.status,
                    "output": obs.result.output, "error": obs.result.error,
                })
        if self._planner and tool_results:
            try:
                return await asyncio.wait_for(
                    self._planner.generate_summary(run.user_message, tool_results),
                    timeout=30.0,
                )
            except Exception as exc:
                logger.warning("Partial summary failed: %s", exc)
        return "Task partially completed. Check tool traces for details."

    async def _compensate_completed_steps(self, run: Run) -> list[ToolResult]:
        """Run saga compensation on all successfully completed mutating steps.

        Walks completed PlanSteps in reverse order and calls each tool's
        ``compensate()`` method. Read-only tools return ``not_applicable``.
        """
        if not run.plan or not run.plan.steps:
            return []
        context = ToolContext(
            workspace_root=str(self._workspace), run_id=run.run_id,
            step_id="compensation", db_path=str(self._db_path),
        )
        results = await self._executor.compensate_steps(run.plan.steps, context)
        for r in results:
            if r.status == "success":
                logger.info("Compensated %s in run %s", r.tool_name, run.run_id)
            elif r.status != "not_applicable":
                logger.warning("Compensation failed for %s: %s", r.tool_name, r.error)
        return results

    # ------------------------------------------------------------------
    # Plan-and-execute (legacy path, use_react=False)
    # ------------------------------------------------------------------

    async def _plan_and_execute(self, run: Run) -> None:
        """Original plan-all-upfront-then-execute path."""
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

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

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
        if approved and not self._settings.use_react:
            # Legacy path only — ReAct loop resumes via _wait_for_approval
            run = await self.get_run(run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                logger.info("Resuming execution for run %s after approval", run_id)
                task = asyncio.create_task(self._resume_after_approval(run, step_id))
                task.add_done_callback(self._task_done)

        return await self.get_run(run_id)

    async def _resume_after_approval(self, run: Run, approved_step_id: str) -> None:
        """Resume a run after approval (legacy plan-and-execute path only)."""
        try:
            if not run.plan:
                return
            tool_results: list[dict[str, Any]] = []
            found_approved = False
            for step in run.plan.steps:
                if step.step_id == approved_step_id:
                    found_approved = True
                if not found_approved:
                    if step.result and step.result.status == "success":
                        tool_results.append({"tool": step.tool, "status": step.result.status,
                                              "output": step.result.output, "error": step.result.error})
                    continue
                if step.status in (StepStatus.COMPLETED, StepStatus.FAILED):
                    continue
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

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _save_run(self, run: Run) -> None:
        run.updated_at = datetime.now(timezone.utc).isoformat()
        plan_json = run.plan.model_dump_json() if run.plan else None
        observations_json = json.dumps(
            [o.model_dump() for o in run.observations], default=str
        ) if run.observations else "[]"
        conn = await get_connection(self._db_path)
        try:
            existing = await conn.execute_fetchall("SELECT id FROM runs WHERE id=?", (run.run_id,))
            if existing:
                await conn.execute(
                    "UPDATE runs SET status=?, plan=?, final_response=?, updated_at=?, "
                    "iterations=?, max_iterations=?, observations=? WHERE id=?",
                    (run.status.value, plan_json, run.final_response, run.updated_at,
                     run.iterations, run.max_iterations, observations_json, run.run_id))
            else:
                await conn.execute(
                    "INSERT INTO runs (id,session_id,workspace_id,status,user_message,plan,"
                    "final_response,created_at,updated_at,iterations,max_iterations,observations) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run.run_id, run.session_id, run.workspace_id, run.status.value,
                     run.user_message, plan_json, run.final_response, run.created_at,
                     run.updated_at, run.iterations, run.max_iterations, observations_json))
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
        observations = []
        obs_raw = row["observations"] if "observations" in row.keys() else None
        if obs_raw:
            try:
                obs_list = json.loads(obs_raw)
                observations = [Observation.model_validate(o) for o in obs_list]
            except Exception:
                pass
        iterations = row["iterations"] if "iterations" in row.keys() else 0
        max_iterations = row["max_iterations"] if "max_iterations" in row.keys() else 10
        return Run(
            run_id=row["id"], session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            status=RunStatus(row["status"]), user_message=row["user_message"],
            plan=plan, final_response=row["final_response"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            iterations=iterations or 0, max_iterations=max_iterations or 10,
            observations=observations,
        )
