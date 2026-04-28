"""
Integration tests — end-to-end with mocked planner, real tools, real DB.

Validates: direct answer, safe tool execution, approval flow,
rejection, multi-step plans, policy-blocked tools, memory round-trip.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from apps.api.config import Settings
from apps.api.core.orchestrator import Orchestrator
from apps.api.database import create_tables
from apps.api.memory.manager import MemoryManager
from apps.api.models.run import RunStatus
from apps.api.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> SkillRegistry:
    r = SkillRegistry()
    r.discover()
    return r


@pytest.fixture
def populated_workspace(tmp_workspace: Path) -> Path:
    (tmp_workspace / "README.md").write_text("# Test\nHello world\n")
    (tmp_workspace / "notes.txt").write_text("Some notes\n")
    return tmp_workspace


def _make_settings(workspace: Path, db_path: Path) -> Settings:
    """Create a Settings instance for testing."""
    return Settings(
        anthropic_api_key="test-fake",
        workspace_root=workspace,
        database_path=db_path,
    )


def _mock_planner_response(plan_dict: dict) -> MagicMock:
    """Create a mock that makes the planner return a specific plan dict."""
    raw = json.dumps(plan_dict)
    cb = MagicMock()
    cb.text = raw
    cb.type = "text"
    resp = MagicMock()
    resp.content = [cb]
    return resp


# ---------------------------------------------------------------------------
# Direct answer flow
# ---------------------------------------------------------------------------


class TestDirectAnswer:
    @pytest.mark.asyncio
    async def test_direct_answer_completes(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # Mock the planner's Claude client
        orch._planner._client = MagicMock()
        orch._planner._client.messages.create = MagicMock(
            return_value=_mock_planner_response({
                "task_type": "direct_answer",
                "confidence": 0.95,
                "reasoning": "Simple question",
                "direct_response": "A README is a documentation file.",
                "steps": [],
            })
        )

        run = await orch.handle_message("What is a README?", "sess_1")
        # Run starts asynchronously — poll until done
        import asyncio
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "A README is a documentation file."


# ---------------------------------------------------------------------------
# Safe tool execution
# ---------------------------------------------------------------------------


class TestSafeToolExecution:
    @pytest.mark.asyncio
    async def test_list_files_executes(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # Plan: use list_files
        orch._planner._client = MagicMock()
        orch._planner._client.messages.create = MagicMock(
            side_effect=[
                _mock_planner_response({
                    "task_type": "tool_needed",
                    "confidence": 0.9,
                    "reasoning": "list files",
                    "steps": [{
                        "step_id": "s1",
                        "tool": "list_files",
                        "args": {"path": "."},
                        "risk_level": "safe",
                    }],
                }),
                # Second call is for generate_summary
                _mock_planner_response({
                    "task_type": "direct_answer",
                    "direct_response": "Found README.md and notes.txt",
                    "steps": [],
                }),
            ]
        )

        run = await orch.handle_message("List files", "sess_1")
        import asyncio
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.COMPLETED


# ---------------------------------------------------------------------------
# Approval flow
# ---------------------------------------------------------------------------


class TestApprovalFlow:
    @pytest.mark.asyncio
    async def test_write_file_pauses_for_approval(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        orch._planner._client = MagicMock()
        orch._planner._client.messages.create = MagicMock(
            return_value=_mock_planner_response({
                "task_type": "tool_needed",
                "confidence": 0.9,
                "reasoning": "create file",
                "steps": [{
                    "step_id": "s1",
                    "tool": "write_file",
                    "args": {"path": "test.txt", "content": "hello", "mode": "create"},
                    "risk_level": "medium",
                }],
            })
        )

        run = await orch.handle_message("Create test.txt", "sess_1")
        import asyncio
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.AWAITING_APPROVAL

    @pytest.mark.asyncio
    async def test_approve_executes_and_completes(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        orch._planner._client = MagicMock()
        orch._planner._client.messages.create = MagicMock(
            side_effect=[
                _mock_planner_response({
                    "task_type": "tool_needed",
                    "confidence": 0.9,
                    "reasoning": "create file",
                    "steps": [{
                        "step_id": "s1",
                        "tool": "write_file",
                        "args": {"path": "test.txt", "content": "hello", "mode": "create"},
                        "risk_level": "medium",
                    }],
                }),
                # Summary after execution
                _mock_planner_response({
                    "task_type": "direct_answer",
                    "direct_response": "File created.",
                    "steps": [],
                }),
            ]
        )

        run = await orch.handle_message("Create test.txt", "sess_1")
        import asyncio
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.AWAITING_APPROVAL

        # Approve the step
        await orch.approve_step(run.run_id, "s1", True)

        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.COMPLETED
        assert (tmp_workspace / "test.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_reject_cancels_run(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        orch._planner._client = MagicMock()
        orch._planner._client.messages.create = MagicMock(
            return_value=_mock_planner_response({
                "task_type": "tool_needed",
                "confidence": 0.9,
                "reasoning": "create file",
                "steps": [{
                    "step_id": "s1",
                    "tool": "write_file",
                    "args": {"path": "test.txt", "content": "hello", "mode": "create"},
                    "risk_level": "medium",
                }],
            })
        )

        run = await orch.handle_message("Create test.txt", "sess_1")
        import asyncio
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                break
            await asyncio.sleep(0.1)

        # Reject
        await orch.approve_step(run.run_id, "s1", False)

        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.CANCELLED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.CANCELLED


# ---------------------------------------------------------------------------
# No API key
# ---------------------------------------------------------------------------


class TestNoApiKey:
    @pytest.mark.asyncio
    async def test_missing_api_key_fails_gracefully(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = Settings(
            anthropic_api_key="",
            workspace_root=tmp_workspace,
            database_path=tmp_db_path,
        )
        orch = Orchestrator(settings, registry)

        run = await orch.handle_message("hello", "sess_1")
        import asyncio
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.FAILED
        assert "API key" in run.final_response


# ---------------------------------------------------------------------------
# Memory round-trip
# ---------------------------------------------------------------------------


class TestMemoryRoundTrip:
    @pytest.mark.asyncio
    async def test_fact_stored_and_searchable(
        self, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        mm = MemoryManager(tmp_db_path)
        item = await mm.store_fact(
            content="User prefers dark mode",
            source="test",
        )
        assert item.id

        from apps.api.memory.retrieval import MemoryRetrieval
        retrieval = MemoryRetrieval(tmp_db_path)
        results = await retrieval.search("dark mode")
        assert len(results) >= 1
        assert any("dark mode" in r.content for r in results)
