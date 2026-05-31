"""Tests for the explain_run skill."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.api.database import create_tables, get_connection
from apps.api.models.run import (
    Goal,
    GoalStatus,
    Observation,
    Plan,
    PlanStep,
    ReflectionResult,
    RiskLevel,
    Run,
    RunStatus,
    StepStatus,
    ToolResult,
)
from apps.api.skills.base import ToolContext
from apps.api.skills.explain_run import ExplainRunTool


# ── Helpers ────────────────────────────────────────────────


def _ctx(workspace: Path, db_path: Path) -> ToolContext:
    return ToolContext(
        workspace_root=str(workspace),
        run_id="test_run",
        step_id="test_step",
        db_path=str(db_path),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _insert_run(db_path: Path, run: Run) -> None:
    """Insert a run directly into the database."""
    plan_json = run.plan.model_dump_json() if run.plan else None
    obs_json = json.dumps([o.model_dump() for o in run.observations], default=str)
    reflection_json = run.reflection.model_dump_json() if run.reflection else None
    conn = await get_connection(db_path)
    try:
        await conn.execute(
            "INSERT INTO runs (id,session_id,workspace_id,status,user_message,"
            "plan,final_response,created_at,updated_at,iterations,max_iterations,"
            "observations,context_window,model_name,reflection,parent_run_id,depth) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.run_id, run.session_id, run.workspace_id, run.status.value,
                run.user_message, plan_json, run.final_response,
                run.created_at, run.updated_at,
                run.iterations, run.max_iterations, obs_json,
                run.context_window, run.model_name, reflection_json,
                run.parent_run_id, run.depth,
            ),
        )
        await conn.commit()
    finally:
        await conn.close()


async def _insert_audit_event(
    db_path: Path, run_id: str, event_type: str, data: dict | None = None
) -> None:
    conn = await get_connection(db_path)
    try:
        await conn.execute(
            "INSERT INTO audit_events (id, event_type, run_id, step_id, data, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                f"evt_{uuid.uuid4().hex[:12]}",
                event_type,
                run_id,
                None,
                json.dumps(data or {}),
                _now(),
            ),
        )
        await conn.commit()
    finally:
        await conn.close()


def _make_completed_run(
    run_id: str = "run_test123",
    observations: list[Observation] | None = None,
    reflection: ReflectionResult | None = None,
    parent_run_id: str | None = None,
    depth: int = 0,
    plan: Plan | None = None,
    final_response: str = "Here is the answer.",
    status: RunStatus = RunStatus.COMPLETED,
    user_message: str = "List files in the workspace",
) -> Run:
    """Create a completed run with sensible defaults."""
    now = _now()
    if observations is None:
        observations = [
            Observation(
                step_id="step_1",
                iteration=1,
                tool="list_files",
                args={"path": "."},
                reasoning="User wants to see files",
                user_announcement="Listing files...",
                result=ToolResult(
                    tool_name="list_files",
                    status="success",
                    risk_level=RiskLevel.SAFE,
                    input={"path": "."},
                    output={"entries": [{"name": "README.md", "kind": "file"}], "total": 1},
                    started_at=now,
                    finished_at=now,
                ),
                timestamp=now,
            ),
        ]
    if plan is None:
        plan = Plan(
            task_type="tool_needed",
            confidence=0.95,
            reasoning="User wants to list files, using list_files tool.",
            steps=[
                PlanStep(
                    step_id="step_1",
                    tool="list_files",
                    args={"path": "."},
                    risk_level=RiskLevel.SAFE,
                    status=StepStatus.COMPLETED,
                    reasoning="List files to show workspace contents",
                ),
            ],
            goals=[
                Goal(goal_id="goal_1", description="List workspace files", status=GoalStatus.DONE),
            ],
        )
    return Run(
        run_id=run_id,
        session_id="test_session",
        workspace_id="default",
        status=status,
        user_message=user_message,
        plan=plan,
        final_response=final_response,
        created_at=now,
        updated_at=now,
        iterations=1,
        max_iterations=10,
        observations=observations,
        model_name="claude-sonnet-4-6",
        reflection=reflection,
        parent_run_id=parent_run_id,
        depth=depth,
    )


# ── Test class ─────────────────────────────────────────────


class TestExplainRun:
    """Tests for ExplainRunTool."""

    @pytest.fixture(autouse=True)
    async def setup_db(self, tmp_path: Path):
        """Create tables for every test."""
        self.db_path = tmp_path / "test.db"
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        await create_tables(self.db_path)

    def _tool_ctx(self) -> ToolContext:
        return _ctx(self.workspace, self.db_path)

    # ── Basic completed run ──

    @pytest.mark.asyncio
    async def test_completed_run_with_observations(self):
        """A standard completed run produces a valid detailed explanation."""
        run = _make_completed_run()
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": run.run_id}, self._tool_ctx())

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "## Intent & Context" in explanation
        assert "List files in the workspace" in explanation
        assert "## Decision Chain" in explanation
        assert "list_files" in explanation
        assert "## Final Answer" in explanation

    # ── Direct answer (no tools) ──

    @pytest.mark.asyncio
    async def test_direct_answer_run(self):
        """A direct_answer run with no observations explains correctly."""
        run = _make_completed_run(
            observations=[],
            plan=Plan(
                task_type="direct_answer",
                confidence=0.99,
                reasoning="This is a knowledge question.",
                direct_response="A README is a documentation file.",
            ),
            user_message="What is a README file?",
            final_response="A README is a documentation file.",
        )
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": run.run_id}, self._tool_ctx())

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "direct_answer" in explanation
        assert "No tools were used" in explanation

    # ── Delegated run (parent + child) ──

    @pytest.mark.asyncio
    async def test_delegated_run(self):
        """A run with child runs includes a delegation section."""
        parent = _make_completed_run(run_id="run_parent")
        child = _make_completed_run(
            run_id="run_child",
            parent_run_id="run_parent",
            depth=1,
            user_message="Sub-task: read README",
            final_response="README contains project docs.",
        )
        await _insert_run(self.db_path, parent)
        await _insert_run(self.db_path, child)

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": "run_parent"}, self._tool_ctx())

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "## Delegation" in explanation
        assert "run_child" in explanation
        assert "Sub-task" in explanation

    # ── Failed run ──

    @pytest.mark.asyncio
    async def test_failed_run(self):
        """A failed run is explainable."""
        run = _make_completed_run(
            status=RunStatus.FAILED,
            final_response="Task failed due to an error.",
            observations=[
                Observation(
                    step_id="step_1",
                    iteration=1,
                    tool="read_file",
                    args={"path": "missing.txt"},
                    reasoning="Try to read the requested file",
                    result=ToolResult(
                        tool_name="read_file",
                        status="error",
                        risk_level=RiskLevel.SAFE,
                        input={"path": "missing.txt"},
                        error="File not found: missing.txt",
                        started_at=_now(),
                        finished_at=_now(),
                    ),
                    timestamp=_now(),
                ),
            ],
        )
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": run.run_id}, self._tool_ctx())

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "failed" in explanation.lower()
        assert "Error" in explanation

    # ── Cancelled run ──

    @pytest.mark.asyncio
    async def test_cancelled_run(self):
        """A cancelled run is explainable."""
        run = _make_completed_run(
            status=RunStatus.CANCELLED,
            final_response="Run cancelled by user.",
        )
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": run.run_id}, self._tool_ctx())

        assert result.status == "success"
        assert result.output["status"] == "cancelled"

    # ── Invalid run ID ──

    @pytest.mark.asyncio
    async def test_invalid_run_id(self):
        """Requesting a non-existent run returns an error."""
        tool = ExplainRunTool()
        result = await tool.execute({"run_id": "run_nonexistent"}, self._tool_ctx())

        assert result.status == "error"
        assert "not found" in result.error.lower()

    # ── In-progress run ──

    @pytest.mark.asyncio
    async def test_in_progress_run_rejected(self):
        """An in-progress run cannot be explained."""
        run = _make_completed_run(status=RunStatus.RUNNING)
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": run.run_id}, self._tool_ctx())

        assert result.status == "error"
        assert "still in progress" in result.error.lower()

    # ── Empty run_id ──

    @pytest.mark.asyncio
    async def test_empty_run_id(self):
        """Empty run_id returns an error."""
        tool = ExplainRunTool()
        result = await tool.execute({"run_id": ""}, self._tool_ctx())

        assert result.status == "error"
        assert "required" in result.error.lower()

    # ── Detail levels ──

    @pytest.mark.asyncio
    async def test_summary_level(self):
        """Summary level produces a compact narrative paragraph, not sections."""
        run = _make_completed_run()
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute(
            {"run_id": run.run_id, "detail_level": "summary"}, self._tool_ctx()
        )

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert result.output["detail_level"] == "summary"
        # Summary should be a narrative paragraph, NOT sectioned markdown
        assert "##" not in explanation
        # Should contain key facts in prose form
        assert "The user asked" in explanation
        assert "list_files" in explanation
        assert "confidence" in explanation.lower()
        assert "iterations" in explanation.lower()

    @pytest.mark.asyncio
    async def test_detailed_level(self):
        """Detailed level uses sectioned markdown with per-step reasoning."""
        run = _make_completed_run()
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute(
            {"run_id": run.run_id, "detail_level": "detailed"}, self._tool_ctx()
        )

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "## Debug Data" not in explanation
        # Detailed uses markdown sections (summary does not)
        assert "## Intent & Context" in explanation
        assert "## Decision Chain" in explanation
        assert "## Final Answer" in explanation
        # Detailed includes per-step reasoning
        assert "Why" in explanation or "reasoning" in explanation.lower()

    @pytest.mark.asyncio
    async def test_debug_level(self):
        """Debug level includes raw observations and audit events."""
        run = _make_completed_run()
        await _insert_run(self.db_path, run)
        await _insert_audit_event(
            self.db_path, run.run_id, "run_created", {"message": "test"}
        )

        tool = ExplainRunTool()
        result = await tool.execute(
            {"run_id": run.run_id, "detail_level": "debug"}, self._tool_ctx()
        )

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "## Debug Data" in explanation
        assert "Raw Observations" in explanation
        assert "Audit Events" in explanation

    # ── Reflection section ──

    @pytest.mark.asyncio
    async def test_run_with_reflection(self):
        """A run with reflection data includes the reflection section."""
        reflection = ReflectionResult(
            overall_score=0.85,
            completeness=0.9,
            accuracy=0.8,
            clarity=0.85,
            issues=["Could be more concise"],
            suggestion="Shorten the response",
            improved=True,
            reentry=False,
            attempt=0,
        )
        run = _make_completed_run(reflection=reflection)
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": run.run_id}, self._tool_ctx())

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "## Self-Reflection" in explanation
        assert "0.85" in explanation
        assert "rewritten" in explanation.lower()

    @pytest.mark.asyncio
    async def test_run_without_reflection(self):
        """A run without reflection omits that section."""
        run = _make_completed_run(reflection=None)
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": run.run_id}, self._tool_ctx())

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "## Self-Reflection" not in explanation

    # ── Goals section ──

    @pytest.mark.asyncio
    async def test_run_with_goals(self):
        """Goals are listed in the explanation."""
        run = _make_completed_run()
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": run.run_id}, self._tool_ctx())

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "## Goals" in explanation
        assert "goal_1" in explanation
        assert "✅" in explanation  # done status

    # ── Manifest ──

    def test_manifest(self):
        """ExplainRunTool has the correct manifest."""
        tool = ExplainRunTool()
        m = tool.manifest()
        assert m.name == "explain_run"
        assert m.risk_level == RiskLevel.SAFE
        assert m.approval_required is False
        assert "run_id" in m.input_schema.get("required", [])

    # ── No DB path ──

    @pytest.mark.asyncio
    async def test_no_db_path(self):
        """Returns error when db_path is not configured."""
        tool = ExplainRunTool()
        ctx = ToolContext(workspace_root=str(self.workspace), db_path="")
        result = await tool.execute({"run_id": "run_test"}, ctx)
        assert result.status == "error"
        assert "database" in result.error.lower()

    # ── Multiple observations ──

    @pytest.mark.asyncio
    async def test_multi_step_observations(self):
        """A run with multiple observations lists them all."""
        now = _now()
        observations = [
            Observation(
                step_id="step_1", iteration=1, tool="read_file",
                args={"path": "README.md"}, reasoning="Read the file first",
                result=ToolResult(
                    tool_name="read_file", status="success",
                    input={"path": "README.md"},
                    output={"content": "# Hello", "lines": 1},
                    started_at=now, finished_at=now,
                ),
                timestamp=now,
            ),
            Observation(
                step_id="step_2", iteration=2, tool="write_file",
                args={"path": "notes.txt", "content": "summary"},
                reasoning="Write the summary",
                result=ToolResult(
                    tool_name="write_file", status="success",
                    risk_level=RiskLevel.MEDIUM,
                    input={"path": "notes.txt"},
                    output={"path": "notes.txt", "written": True},
                    started_at=now, finished_at=now,
                ),
                timestamp=now,
            ),
            Observation(
                step_id="step_3", iteration=3, tool=None,
                reasoning="All done, providing final answer",
                timestamp=now,
            ),
        ]
        run = _make_completed_run(observations=observations)
        run.iterations = 3
        await _insert_run(self.db_path, run)

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": run.run_id}, self._tool_ctx())

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "read_file" in explanation
        assert "write_file" in explanation
        assert "Final Answer" in explanation
        assert "Iteration 1" in explanation
        assert "Iteration 2" in explanation

    # ── Audit events in debug ──

    @pytest.mark.asyncio
    async def test_audit_events_in_debug(self):
        """Debug level surfaces audit events."""
        run = _make_completed_run()
        await _insert_run(self.db_path, run)
        await _insert_audit_event(
            self.db_path, run.run_id, "memory_context_retrieved",
            {"fact_count": 2, "episode_count": 1, "strategy_count": 0},
        )
        await _insert_audit_event(
            self.db_path, run.run_id, "tool_executed",
            {"tool": "list_files", "status": "success"},
        )

        tool = ExplainRunTool()
        result = await tool.execute(
            {"run_id": run.run_id, "detail_level": "debug"}, self._tool_ctx()
        )

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "memory_context_retrieved" in explanation
        assert "tool_executed" in explanation

    # ── Memory context in intent section ──

    @pytest.mark.asyncio
    async def test_memory_context_in_intent(self):
        """Memory context from audit events is surfaced in the intent section."""
        run = _make_completed_run()
        await _insert_run(self.db_path, run)
        await _insert_audit_event(
            self.db_path, run.run_id, "memory_context_retrieved",
            {"fact_count": 3, "episode_count": 2, "strategy_count": 1},
        )

        tool = ExplainRunTool()
        result = await tool.execute({"run_id": run.run_id}, self._tool_ctx())

        assert result.status == "success"
        explanation = result.output["explanation"]
        assert "6 items" in explanation  # 3+2+1
        assert "3 facts" in explanation
