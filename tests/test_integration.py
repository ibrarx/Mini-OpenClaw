"""
Tests for the orchestrator — end-to-end pipeline with mocked planner.

Validates: direct answer flow, tool execution, approval flow,
max steps guard, episode memory creation, assistant message storage.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from apps.api.core.audit import AuditLogger
from apps.api.core.events import EventEmitter
from apps.api.core.executor import Executor
from apps.api.core.orchestrator import MAX_STEPS_PER_RUN, Orchestrator
from apps.api.core.planner import Planner, PlannerError, PlannerResponse
from apps.api.core.policy import PolicyEngine
from apps.api.database import create_tables
from apps.api.models.run import Plan, RunStatus, TaskType
from apps.api.models.step import RiskLevel, RunStep, StepStatus
from apps.api.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_db_path):
    """Create a test database and return an open connection."""
    await create_tables(tmp_db_path)
    conn = await aiosqlite.connect(str(tmp_db_path))
    conn.row_factory = aiosqlite.Row
    yield conn
    await conn.close()


@pytest.fixture
def registry():
    r = SkillRegistry()
    r.discover()
    return r


@pytest.fixture
def populated_workspace(tmp_workspace):
    """Workspace with sample files for tool testing."""
    (tmp_workspace / "README.md").write_text("# Test\nHello world\n")
    (tmp_workspace / "notes.txt").write_text("Some notes\n")
    return tmp_workspace


def _make_planner_response(plan: Plan, raw: str = "{}") -> PlannerResponse:
    return PlannerResponse(plan=plan, raw_model_output=raw)


def _build_orchestrator(db, registry, workspace, planner_resp=None, planner_error=None):
    """Build an orchestrator with a mocked planner."""
    planner = Planner(api_key="", model="test", registry=registry)
    if planner_resp is not None:
        planner.create_plan = AsyncMock(return_value=planner_resp)
    elif planner_error is not None:
        planner.create_plan = AsyncMock(side_effect=planner_error)

    policy = PolicyEngine(workspace_root=str(workspace))
    audit = AuditLogger(db)
    events = EventEmitter()
    executor = Executor(registry=registry, audit=audit)

    return Orchestrator(
        db=db, planner=planner, policy=policy,
        executor=executor, audit=audit, events=events,
    )


# ---------------------------------------------------------------------------
# Direct answer flow
# ---------------------------------------------------------------------------

class TestDirectAnswer:
    @pytest.mark.asyncio
    async def test_direct_answer_completes(self, db, registry, tmp_workspace):
        plan = Plan(
            task_type=TaskType.DIRECT_ANSWER,
            confidence=0.95,
            reasoning="Simple question",
            direct_response="A README is a documentation file.",
        )
        resp = _make_planner_response(plan)
        orch = _build_orchestrator(db, registry, tmp_workspace, planner_resp=resp)

        run = await orch.process_message("What is a README?", "sess_1")
        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "A README is a documentation file."

    @pytest.mark.asyncio
    async def test_direct_answer_stores_assistant_message(self, db, registry, tmp_workspace):
        plan = Plan(
            task_type=TaskType.DIRECT_ANSWER,
            confidence=0.9,
            reasoning="Q",
            direct_response="Answer here.",
        )
        orch = _build_orchestrator(
            db, registry, tmp_workspace,
            planner_resp=_make_planner_response(plan),
        )
        run = await orch.process_message("test", "sess_1")

        rows = await db.execute_fetchall(
            "SELECT * FROM messages WHERE role='assistant' AND run_id=?",
            (run.run_id,),
        )
        assert len(rows) == 1
        assert dict(rows[0])["content"] == "Answer here."


# ---------------------------------------------------------------------------
# Safe tool execution
# ---------------------------------------------------------------------------

class TestSafeToolExecution:
    @pytest.mark.asyncio
    async def test_list_files_auto_executes(self, db, registry, populated_workspace):
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            reasoning="List files",
            steps=[RunStep(
                step_id="s1", tool="list_files",
                args={"path": "."}, risk_level=RiskLevel.SAFE,
            )],
        )
        orch = _build_orchestrator(
            db, registry, populated_workspace,
            planner_resp=_make_planner_response(plan),
        )
        run = await orch.process_message("List files", "sess_1")
        assert run.status == RunStatus.COMPLETED
        assert "README.md" in run.final_response


# ---------------------------------------------------------------------------
# Approval flow
# ---------------------------------------------------------------------------

class TestApprovalFlow:
    @pytest.mark.asyncio
    async def test_write_file_pauses_for_approval(self, db, registry, tmp_workspace):
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            reasoning="Create file",
            steps=[RunStep(
                step_id="s1", tool="write_file",
                args={"path": "test.txt", "content": "hello", "mode": "create"},
                risk_level=RiskLevel.MEDIUM,
            )],
        )
        orch = _build_orchestrator(
            db, registry, tmp_workspace,
            planner_resp=_make_planner_response(plan),
        )
        run = await orch.process_message("Create test.txt", "sess_1")
        assert run.status == RunStatus.AWAITING_APPROVAL

        # Verify approval record in DB
        rows = await db.execute_fetchall(
            "SELECT * FROM approvals WHERE run_id=?", (run.run_id,)
        )
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_approve_executes_and_completes(self, db, registry, tmp_workspace):
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            reasoning="Create file",
            steps=[RunStep(
                step_id="s1", tool="write_file",
                args={"path": "test.txt", "content": "hello", "mode": "create"},
                risk_level=RiskLevel.MEDIUM,
            )],
        )
        orch = _build_orchestrator(
            db, registry, tmp_workspace,
            planner_resp=_make_planner_response(plan),
        )
        run = await orch.process_message("Create test.txt", "sess_1")
        assert run.status == RunStatus.AWAITING_APPROVAL

        # Approve
        run = await orch.approve_step(run.run_id, "s1", True)
        assert run.status == RunStatus.COMPLETED
        assert (tmp_workspace / "test.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_reject_cancels_run(self, db, registry, tmp_workspace):
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            reasoning="Create file",
            steps=[RunStep(
                step_id="s1", tool="write_file",
                args={"path": "test.txt", "content": "hello", "mode": "create"},
                risk_level=RiskLevel.MEDIUM,
            )],
        )
        orch = _build_orchestrator(
            db, registry, tmp_workspace,
            planner_resp=_make_planner_response(plan),
        )
        run = await orch.process_message("Create test.txt", "sess_1")
        run = await orch.approve_step(run.run_id, "s1", False)
        assert run.status == RunStatus.CANCELLED


# ---------------------------------------------------------------------------
# Planner failure
# ---------------------------------------------------------------------------

class TestPlannerFailure:
    @pytest.mark.asyncio
    async def test_planner_error_fails_run(self, db, registry, tmp_workspace):
        orch = _build_orchestrator(
            db, registry, tmp_workspace,
            planner_error=PlannerError("API down"),
        )
        run = await orch.process_message("do something", "sess_1")
        assert run.status == RunStatus.FAILED
        assert "API down" in run.final_response


# ---------------------------------------------------------------------------
# Forbidden tool
# ---------------------------------------------------------------------------

class TestForbiddenTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_skipped(self, db, registry, tmp_workspace):
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            reasoning="hack",
            steps=[RunStep(step_id="s1", tool="hack", args={})],
        )
        orch = _build_orchestrator(
            db, registry, tmp_workspace,
            planner_resp=_make_planner_response(plan),
        )
        run = await orch.process_message("hack the planet", "sess_1")
        assert run.status == RunStatus.COMPLETED
        # Step was skipped, so no meaningful results
        assert "No results" in run.final_response


# ---------------------------------------------------------------------------
# Max steps guard
# ---------------------------------------------------------------------------

class TestMaxSteps:
    @pytest.mark.asyncio
    async def test_max_steps_limits_execution(self, db, registry, populated_workspace):
        """Generate more steps than MAX_STEPS_PER_RUN — only first N execute."""
        steps = [
            RunStep(
                step_id=f"s{i}",
                tool="list_files",
                args={"path": "."},
                risk_level=RiskLevel.SAFE,
            )
            for i in range(MAX_STEPS_PER_RUN + 5)
        ]
        plan = Plan(
            task_type=TaskType.MULTI_STEP,
            confidence=0.9,
            reasoning="many steps",
            steps=steps,
        )
        orch = _build_orchestrator(
            db, registry, populated_workspace,
            planner_resp=_make_planner_response(plan),
        )
        run = await orch.process_message("lots of work", "sess_1")
        assert run.status == RunStatus.COMPLETED

        # Only MAX_STEPS_PER_RUN steps should have completed
        completed = [
            s for s in run.plan.steps if s.status == StepStatus.COMPLETED
        ]
        assert len(completed) == MAX_STEPS_PER_RUN


# ---------------------------------------------------------------------------
# Episode memory
# ---------------------------------------------------------------------------

class TestEpisodeMemory:
    @pytest.mark.asyncio
    async def test_episode_stored_after_tool_run(self, db, registry, populated_workspace):
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            reasoning="List files",
            steps=[RunStep(
                step_id="s1", tool="list_files",
                args={"path": "."}, risk_level=RiskLevel.SAFE,
            )],
        )
        orch = _build_orchestrator(
            db, registry, populated_workspace,
            planner_resp=_make_planner_response(plan),
        )
        await orch.process_message("List files in workspace", "sess_1")

        rows = await db.execute_fetchall(
            "SELECT * FROM memory_items WHERE memory_type='episode'"
        )
        assert len(rows) >= 1
        content = dict(rows[0])["content"]
        assert "list_files" in content

    @pytest.mark.asyncio
    async def test_no_episode_for_direct_answer(self, db, registry, tmp_workspace):
        plan = Plan(
            task_type=TaskType.DIRECT_ANSWER,
            confidence=0.95,
            reasoning="Simple Q",
            direct_response="42",
        )
        orch = _build_orchestrator(
            db, registry, tmp_workspace,
            planner_resp=_make_planner_response(plan),
        )
        await orch.process_message("What is 6*7?", "sess_1")

        rows = await db.execute_fetchall(
            "SELECT * FROM memory_items WHERE memory_type='episode'"
        )
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_audit_events_logged(self, db, registry, populated_workspace):
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            reasoning="List files",
            steps=[RunStep(
                step_id="s1", tool="list_files",
                args={"path": "."}, risk_level=RiskLevel.SAFE,
            )],
        )
        orch = _build_orchestrator(
            db, registry, populated_workspace,
            planner_resp=_make_planner_response(plan),
        )
        run = await orch.process_message("List files", "sess_1")

        events = await db.execute_fetchall(
            "SELECT event_type FROM audit_events WHERE run_id=?",
            (run.run_id,),
        )
        event_types = {dict(e)["event_type"] for e in events}
        assert "run_created" in event_types
        assert "plan_ready" in event_types
        assert "policy_decision" in event_types
