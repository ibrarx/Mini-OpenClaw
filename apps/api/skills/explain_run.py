"""skills/explain_run — Explain why the agent made each decision in a past run.

Produces a structured, human-readable causal narrative tracing:
  user intent → memory context → planner reasoning → tool selection →
  observation impact → replan triggers → reflection score → final answer.

Read-only, no approval required.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from apps.api.database import get_connection
from apps.api.models.run import (
    Observation,
    Plan,
    ReflectionResult,
    RiskLevel,
    Run,
    RunStatus,
)
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)


class ExplainRunTool(BaseTool):
    """Generate a causal explanation of an agent run."""

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="explain_run",
            description=(
                "Explain why the agent made each decision in a past run. "
                "Produces a causal narrative from intent to final answer."
            ),
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            input_schema={
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "The ID of the run to explain (e.g. 'run_abc123')",
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["summary", "detailed", "debug"],
                        "description": (
                            "How much detail to include. 'summary' = high-level narrative, "
                            "'detailed' = per-step reasoning, "
                            "'debug' = includes raw observations and audit events"
                        ),
                    },
                },
                "required": ["run_id"],
            },
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        """Build a causal explanation for the given run."""
        started = self._now()
        run_id: str = args.get("run_id", "")
        detail_level: str = args.get("detail_level", "summary")

        if not run_id.strip():
            return self._error(args, "run_id is required", started)

        if detail_level not in ("summary", "detailed", "debug"):
            detail_level = "summary"

        db_path = context.db_path
        if not db_path:
            return self._error(args, "Database path not configured", started)

        try:
            run = await self._load_run(db_path, run_id)
        except Exception as exc:
            logger.warning("Failed to load run %s: %s", run_id, exc)
            return self._error(args, f"Failed to load run: {exc}", started)

        if run is None:
            return self._error(args, f"Run not found: {run_id}", started)

        # Reject in-progress runs
        if run.status in (
            RunStatus.IDLE,
            RunStatus.PLANNING,
            RunStatus.RUNNING,
            RunStatus.REACTING,
            RunStatus.REFLECTING,
            RunStatus.AWAITING_APPROVAL,
        ):
            return self._error(
                args,
                f"Run is still in progress (status: {run.status.value}). "
                "Wait for it to finish before requesting an explanation.",
                started,
            )

        # Load supplementary data
        audit_events = await self._load_audit_events(db_path, run_id)
        child_runs = await self._load_child_runs(db_path, run_id)

        # Build the explanation
        explanation = self._build_explanation(
            run, audit_events, child_runs, detail_level
        )

        return self._success(
            args,
            {
                "run_id": run_id,
                "detail_level": detail_level,
                "status": run.status.value,
                "explanation": explanation,
            },
            started,
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    @staticmethod
    async def _load_run(db_path: str, run_id: str) -> Run | None:
        """Load a run from the database, reusing the orchestrator's parsing."""
        conn = await get_connection(db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT * FROM runs WHERE id=?", (run_id,)
            )
            if not rows:
                return None
            return _row_to_run(rows[0])
        finally:
            await conn.close()

    @staticmethod
    async def _load_audit_events(
        db_path: str, run_id: str
    ) -> list[dict[str, Any]]:
        """Load audit events for a run, ordered chronologically."""
        conn = await get_connection(db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT * FROM audit_events WHERE run_id=? ORDER BY created_at ASC",
                (run_id,),
            )
            events = []
            for r in rows:
                data = {}
                raw = r["data"]
                if raw:
                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        data = {"raw": str(raw)}
                events.append(
                    {
                        "id": r["id"],
                        "event_type": r["event_type"],
                        "step_id": r["step_id"],
                        "data": data,
                        "created_at": r["created_at"],
                    }
                )
            return events
        finally:
            await conn.close()

    @staticmethod
    async def _load_child_runs(
        db_path: str, parent_run_id: str
    ) -> list[Run]:
        """Load child (delegated) runs."""
        conn = await get_connection(db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT * FROM runs WHERE parent_run_id=? ORDER BY created_at ASC",
                (parent_run_id,),
            )
            return [_row_to_run(r) for r in rows]
        finally:
            await conn.close()

    # ------------------------------------------------------------------
    # Explanation builder
    # ------------------------------------------------------------------

    def _build_explanation(
        self,
        run: Run,
        audit_events: list[dict[str, Any]],
        child_runs: list[Run],
        detail_level: str,
    ) -> str:
        """Assemble the markdown explanation from run data."""
        if detail_level == "summary":
            return self._build_summary_narrative(run, child_runs)

        sections: list[str] = []

        sections.append(self._section_intent(run, audit_events, detail_level))
        sections.append(self._section_goals(run, detail_level))
        sections.append(
            self._section_decision_chain(run, audit_events, detail_level)
        )

        if child_runs:
            sections.append(
                self._section_delegation(run, child_runs, detail_level)
            )

        if run.reflection:
            sections.append(
                self._section_reflection(run.reflection, detail_level)
            )

        sections.append(self._section_final_answer(run, detail_level))

        if detail_level == "debug":
            sections.append(self._section_debug(run, audit_events))

        return "\n\n".join(s for s in sections if s)

    # -- Summary narrative (compact paragraph form) --

    def _build_summary_narrative(
        self, run: Run, child_runs: list[Run]
    ) -> str:
        """Build a ~200-word narrative paragraph summarizing the run."""
        parts: list[str] = []

        # Intent
        parts.append(f'The user asked: "{run.user_message}".')

        # Planner assessment
        if run.plan:
            if run.plan.task_type == "direct_answer":
                parts.append(
                    "The planner classified this as a direct knowledge question "
                    f"(confidence: {run.plan.confidence:.0%}) and answered without "
                    "using any tools."
                )
            else:
                parts.append(
                    f"The planner classified this as `{run.plan.task_type}` "
                    f"(confidence: {run.plan.confidence:.0%})."
                )

        # Tool usage summary
        tool_obs = [o for o in run.observations if o.tool is not None]
        if tool_obs:
            tool_names = list(dict.fromkeys(o.tool for o in tool_obs))  # unique, ordered
            successes = sum(1 for o in tool_obs if o.result and o.result.status == "success")
            errors = sum(1 for o in tool_obs if o.result and o.result.status == "error")
            denied = sum(1 for o in tool_obs if o.result and o.result.status in ("denied", "rejected"))

            tools_str = ", ".join(f"`{t}`" for t in tool_names)
            parts.append(f"It used {tools_str} across {len(tool_obs)} step(s).")

            outcome_parts = []
            if successes:
                outcome_parts.append(f"{successes} succeeded")
            if errors:
                outcome_parts.append(f"{errors} failed")
            if denied:
                outcome_parts.append(f"{denied} blocked")
            if outcome_parts:
                parts.append(f"Outcomes: {', '.join(outcome_parts)}.")

        # Goals summary
        if run.plan and run.plan.goals:
            done = sum(1 for g in run.plan.goals if g.status.value == "done")
            total = len(run.plan.goals)
            parts.append(f"Goals: {done}/{total} completed.")

        # Delegation
        if child_runs:
            child_statuses = [c.status.value for c in child_runs]
            parts.append(
                f"Delegated {len(child_runs)} sub-task(s) "
                f"({', '.join(child_statuses)})."
            )

        # Reflection
        if run.reflection:
            parts.append(
                f"Self-reflection scored {run.reflection.overall_score:.0%}."
            )
            if run.reflection.improved:
                parts.append("The answer was rewritten to improve quality.")
            if run.reflection.reentry:
                parts.append("The agent re-entered the loop to take corrective action.")

        # Final status
        parts.append(
            f"Finished in {run.iterations}/{run.max_iterations} iterations "
            f"with status: {run.status.value}."
        )

        return " ".join(parts)

    # -- Section 1: Intent & Context --

    def _section_intent(
        self,
        run: Run,
        audit_events: list[dict[str, Any]],
        detail_level: str,
    ) -> str:
        lines = ["## Intent & Context"]
        lines.append(f"**User request:** {run.user_message}")

        if run.model_name:
            lines.append(f"**Model:** {run.model_name}")

        # Memory context from audit events
        memory_events = [
            e for e in audit_events if e["event_type"] == "memory_context_retrieved"
        ]
        if memory_events and detail_level != "summary":
            data = memory_events[0].get("data", {})
            fact_count = data.get("fact_count", 0)
            episode_count = data.get("episode_count", 0)
            strategy_count = data.get("strategy_count", 0)
            total = fact_count + episode_count + strategy_count
            if total > 0:
                lines.append(
                    f"**Memory context injected:** {total} items "
                    f"({fact_count} facts, {episode_count} episodes, "
                    f"{strategy_count} strategies)"
                )
            else:
                lines.append("**Memory context:** No relevant memories found.")
        elif not memory_events:
            lines.append("**Memory context:** Not recorded in audit log.")

        # Planner's initial assessment
        if run.plan:
            lines.append(
                f"**Planner assessment:** task_type=`{run.plan.task_type}`, "
                f"confidence={run.plan.confidence:.2f}"
            )
            if detail_level != "summary" and run.plan.reasoning:
                lines.append(f"**Planner reasoning:** {run.plan.reasoning}")

        return "\n".join(lines)

    # -- Section 2: Goal Formation --

    def _section_goals(self, run: Run, detail_level: str) -> str:
        if not run.plan or not run.plan.goals:
            if detail_level == "summary":
                return ""
            return "## Goals\nNo explicit goals were set for this run."

        lines = ["## Goals"]
        for g in run.plan.goals:
            status_icon = {
                "done": "✅",
                "in_progress": "🔄",
                "pending": "⏳",
                "skipped": "⏭️",
            }.get(g.status.value, "❓")
            lines.append(f"- {status_icon} **{g.goal_id}**: {g.description} ({g.status.value})")

        if run.plan.replan_count > 0:
            lines.append(f"\n*Replanned {run.plan.replan_count} time(s) during execution.*")

        return "\n".join(lines)

    # -- Section 3: Decision Chain --

    def _section_decision_chain(
        self,
        run: Run,
        audit_events: list[dict[str, Any]],
        detail_level: str,
    ) -> str:
        if not run.observations:
            if run.plan and run.plan.task_type == "direct_answer":
                return (
                    "## Decision Chain\n"
                    "No tools were used. The planner answered directly from its knowledge."
                )
            return "## Decision Chain\nNo observations recorded."

        lines = ["## Decision Chain"]

        # Build a lookup of replan events by iteration for impact analysis
        replan_events = [
            e for e in audit_events if "replan" in e["event_type"]
        ]

        for i, obs in enumerate(run.observations):
            is_final = obs.tool is None
            header = (
                f"### {'Final Answer' if is_final else f'Iteration {obs.iteration}'}"
            )
            lines.append(header)

            if is_final:
                if detail_level != "summary" and obs.reasoning:
                    lines.append(f"**Reasoning:** {obs.reasoning}")
                continue

            lines.append(f"**Tool:** `{obs.tool}`")

            if detail_level != "summary":
                if obs.reasoning:
                    lines.append(f"**Why:** {obs.reasoning}")
                if obs.user_announcement:
                    lines.append(f"**Announced:** {obs.user_announcement}")

            # Outcome
            if obs.result:
                status = obs.result.status
                if status == "success":
                    output_summary = self._summarize_output(
                        obs.result.output, detail_level
                    )
                    lines.append(f"**Outcome:** ✅ Success{output_summary}")
                elif status == "error":
                    lines.append(
                        f"**Outcome:** ❌ Error — {obs.result.error or 'unknown'}"
                    )
                elif status == "denied":
                    lines.append(
                        "**Outcome:** 🚫 Denied by policy"
                    )
                elif status == "rejected":
                    lines.append(
                        "**Outcome:** 👎 Rejected by user"
                    )
                else:
                    lines.append(f"**Outcome:** {status}")

            # Impact: did this trigger a replan?
            if detail_level != "summary":
                triggered_replan = any(
                    e.get("data", {}).get("after_iteration") == obs.iteration
                    for e in replan_events
                )
                if triggered_replan:
                    lines.append("**Impact:** Triggered a replan.")

        return "\n".join(lines)

    # -- Section 4: Delegation --

    def _section_delegation(
        self,
        run: Run,
        child_runs: list[Run],
        detail_level: str,
    ) -> str:
        lines = ["## Delegation"]
        lines.append(f"This run delegated {len(child_runs)} sub-task(s).")

        for child in child_runs:
            lines.append(f"\n### Child: `{child.run_id}`")
            lines.append(f"**Task:** {child.user_message}")
            lines.append(f"**Status:** {child.status.value}")
            lines.append(f"**Depth:** {child.depth}")
            lines.append(f"**Iterations:** {child.iterations}/{child.max_iterations}")

            if child.final_response:
                response_preview = child.final_response
                if detail_level == "summary" and len(response_preview) > 150:
                    response_preview = response_preview[:150] + "…"
                elif detail_level == "detailed" and len(response_preview) > 400:
                    response_preview = response_preview[:400] + "…"
                lines.append(f"**Result:** {response_preview}")

        return "\n".join(lines)

    # -- Section 5: Reflection --

    def _section_reflection(
        self,
        reflection: ReflectionResult,
        detail_level: str,
    ) -> str:
        lines = ["## Self-Reflection"]
        lines.append(
            f"**Overall score:** {reflection.overall_score:.2f} "
            f"(completeness={reflection.completeness:.2f}, "
            f"accuracy={reflection.accuracy:.2f}, "
            f"clarity={reflection.clarity:.2f})"
        )

        if detail_level != "summary":
            if reflection.issues:
                lines.append("**Issues identified:**")
                for issue in reflection.issues:
                    lines.append(f"  - {issue}")
            if reflection.suggestion:
                lines.append(f"**Suggestion:** {reflection.suggestion}")

        action_taken = []
        if reflection.improved:
            action_taken.append("answer was rewritten")
        if reflection.reentry:
            action_taken.append("agent re-entered the loop")
        if action_taken:
            lines.append(f"**Corrective action:** {', '.join(action_taken)}")
        elif reflection.overall_score >= 0.8:
            lines.append("**Corrective action:** None needed (score ≥ 0.8).")
        else:
            lines.append("**Corrective action:** None taken.")

        return "\n".join(lines)

    # -- Section 6: Final Answer --

    def _section_final_answer(self, run: Run, detail_level: str) -> str:
        lines = ["## Final Answer"]

        # Determine answer source
        if run.plan and run.plan.task_type == "direct_answer":
            lines.append("**Source:** Direct answer (no tools used)")
        elif run.iterations >= run.max_iterations:
            lines.append("**Source:** Max iterations reached (graceful degradation)")
        elif run.reflection and run.reflection.improved:
            lines.append("**Source:** Reflection-rewritten answer")
        elif run.observations:
            lines.append("**Source:** Synthesized from tool results")
        else:
            lines.append("**Source:** Unknown")

        lines.append(f"**Status:** {run.status.value}")
        lines.append(f"**Iterations used:** {run.iterations}/{run.max_iterations}")

        if run.final_response:
            if detail_level == "summary":
                preview = run.final_response
                if len(preview) > 200:
                    preview = preview[:200] + "…"
                lines.append(f"\n{preview}")
            else:
                lines.append(f"\n{run.final_response}")

        return "\n".join(lines)

    # -- Debug section --

    def _section_debug(
        self,
        run: Run,
        audit_events: list[dict[str, Any]],
    ) -> str:
        lines = ["## Debug Data"]

        # Raw observations
        lines.append("### Raw Observations")
        for i, obs in enumerate(run.observations):
            lines.append(f"\n**Observation {i} (iteration {obs.iteration}):**")
            obs_dict = obs.model_dump()
            # Truncate large result outputs
            if obs_dict.get("result") and obs_dict["result"].get("output"):
                output_str = json.dumps(obs_dict["result"]["output"], default=str)
                if len(output_str) > 500:
                    obs_dict["result"]["output"] = {"_truncated": output_str[:500] + "…"}
            lines.append(f"```json\n{json.dumps(obs_dict, indent=2, default=str)}\n```")

        # Audit events
        lines.append("\n### Audit Events")
        for evt in audit_events:
            data_str = json.dumps(evt["data"], default=str)
            if len(data_str) > 300:
                data_str = data_str[:300] + "…"
            lines.append(
                f"- `{evt['event_type']}` at {evt['created_at']}: {data_str}"
            )

        return "\n".join(lines)

    # -- Helpers --

    @staticmethod
    def _summarize_output(
        output: dict[str, Any] | None, detail_level: str
    ) -> str:
        """Produce a compact summary of tool output."""
        if not output:
            return ""
        # For summary level, just indicate there was output
        if detail_level == "summary":
            return ""

        # Try to extract the most useful fields
        summary_parts = []
        for key in ("total", "count", "results", "entries", "content", "lines"):
            if key in output:
                val = output[key]
                if isinstance(val, list):
                    summary_parts.append(f"{len(val)} {key}")
                elif isinstance(val, str) and len(val) > 100:
                    summary_parts.append(f"{key}: {val[:100]}…")
                else:
                    summary_parts.append(f"{key}: {val}")
        if summary_parts:
            return " — " + ", ".join(summary_parts)
        return ""


# ------------------------------------------------------------------
# Row-to-Run parser (duplicated from orchestrator to avoid circular import)
# ------------------------------------------------------------------

def _row_to_run(row: aiosqlite.Row) -> Run:
    """Parse a database row into a Run model.

    Mirrors Orchestrator._row_to_run() to avoid importing the orchestrator
    (which pulls in heavy dependencies like the LLM provider).
    """
    plan = None
    if row["plan"]:
        try:
            plan = Plan.model_validate_json(row["plan"])
        except Exception:
            pass

    observations: list[Observation] = []
    obs_raw = row["observations"] if "observations" in row.keys() else None
    if obs_raw:
        try:
            obs_list = json.loads(obs_raw)
            observations = [Observation.model_validate(o) for o in obs_list]
        except Exception:
            pass

    reflection = None
    reflection_raw = row["reflection"] if "reflection" in row.keys() else None
    if reflection_raw:
        try:
            reflection = ReflectionResult.model_validate_json(reflection_raw)
        except Exception:
            pass

    iterations = row["iterations"] if "iterations" in row.keys() else 0
    max_iterations = row["max_iterations"] if "max_iterations" in row.keys() else 10
    context_window = row["context_window"] if "context_window" in row.keys() else 0
    model_name = row["model_name"] if "model_name" in row.keys() else ""

    return Run(
        run_id=row["id"],
        session_id=row["session_id"],
        workspace_id=row["workspace_id"],
        status=RunStatus(row["status"]),
        user_message=row["user_message"],
        plan=plan,
        final_response=row["final_response"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        iterations=iterations or 0,
        max_iterations=max_iterations or 10,
        observations=observations,
        context_window=context_window or 0,
        model_name=model_name or "",
        reflection=reflection,
        parent_run_id=row["parent_run_id"] if "parent_run_id" in row.keys() else None,
        depth=row["depth"] if "depth" in row.keys() else 0,
    )
