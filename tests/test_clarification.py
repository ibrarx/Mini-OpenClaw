"""
Tests for the confidence-gated clarification feature.

Covers:
- Low-confidence plan with questions → AWAITING_CLARIFICATION, ReAct loop NOT started
- clarify endpoint folds answer in and resumes; run completes
- High-confidence plan → no pause, proceeds directly (regression)
- task_type == clarification_needed triggers pause even if confidence is set
- Still-ambiguous after clarification_max_rounds → proceeds best-effort
- Empty questions list → no pause even if confidence is low
- Child/delegated run never pauses for clarification
- clarification_enabled=False → behaves exactly as before
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from apps.api.config import Settings
from apps.api.core.orchestrator import Orchestrator
from apps.api.database import create_tables
from apps.api.models.run import Run, RunStatus, Plan
from apps.api.skills.registry import SkillRegistry


# ── Fixtures ──────────────────────────────────────────


def _make_settings(tmp_path: Path, **overrides) -> Settings:
    """Build Settings with test defaults and optional overrides."""
    defaults = dict(
        workspace_root=tmp_path / "workspace",
        database_path=tmp_path / "test.db",
        anthropic_api_key="test-key",
        use_react=True,
        react_max_iterations=5,
        clarification_enabled=True,
        clarification_threshold=0.5,
        clarification_max_rounds=2,
        react_use_goals=False,
        react_self_reflect=False,
        delegate_enabled=False,
        summary_interval=0,
        dream_interval=0,
    )
    defaults.update(overrides)
    return Settings(**defaults)


@pytest_asyncio.fixture
async def setup(tmp_path: Path):
    """Create workspace, DB, registry, and orchestrator."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Hello\nTest project.")

    settings = _make_settings(tmp_path)
    await create_tables(settings.resolved_database)

    registry = SkillRegistry()
    orch = Orchestrator(settings, registry)
    return orch, settings, workspace


def _mock_create_plan(task_type="tool_needed", confidence=0.9,
                      questions=None, steps=None):
    """Return a dict mimicking Planner.create_plan() output."""
    return {
        "task_type": task_type,
        "confidence": confidence,
        "reasoning": "test",
        "direct_response": None,
        "steps": steps or [],
        "clarifying_questions": questions or [],
    }


def _mock_react_final(response="Done."):
    """Return a dict mimicking a react_step final_answer."""
    return {
        "action": "final_answer",
        "response": response,
        "reasoning": "task complete",
        "_context_meta": {"tokens_used": 100, "context_window": 200000, "compression": "none"},
    }


# ── Tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_confidence_with_questions_pauses(setup):
    """Low-confidence plan WITH questions → AWAITING_CLARIFICATION, ReAct loop NOT started."""
    orch, settings, workspace = setup

    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(return_value=_mock_create_plan(
            confidence=0.3,
            questions=["Which directory?", "Create or overwrite?"],
        ))
        # react_step should NOT be called — the run pauses before the loop
        mock_planner.react_step = AsyncMock(side_effect=AssertionError("Should not be called"))

        run = await orch.handle_message("sess1", "do something ambiguous")
        await orch.wait_pending()

    loaded = await orch.get_run(run.run_id)
    assert loaded is not None
    assert loaded.status == RunStatus.AWAITING_CLARIFICATION
    assert loaded.clarifying_questions == ["Which directory?", "Create or overwrite?"]
    assert loaded.clarification_rounds == 0
    assert loaded.iterations == 0  # ReAct loop never started


@pytest.mark.asyncio
async def test_clarification_needed_task_type_pauses(setup):
    """task_type == clarification_needed triggers pause even with high confidence."""
    orch, settings, workspace = setup

    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(return_value=_mock_create_plan(
            task_type="clarification_needed",
            confidence=0.95,  # high confidence, but task_type overrides
            questions=["What format do you want?"],
        ))
        mock_planner.react_step = AsyncMock(side_effect=AssertionError("Should not be called"))

        run = await orch.handle_message("sess1", "format this")
        await orch.wait_pending()

    loaded = await orch.get_run(run.run_id)
    assert loaded.status == RunStatus.AWAITING_CLARIFICATION
    assert loaded.clarifying_questions == ["What format do you want?"]


@pytest.mark.asyncio
async def test_high_confidence_proceeds_directly(setup):
    """High-confidence plan → no pause, proceeds into ReAct loop directly."""
    orch, settings, workspace = setup

    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(return_value=_mock_create_plan(
            confidence=0.9,
            questions=[],
        ))
        mock_planner.react_step = AsyncMock(return_value=_mock_react_final("All good."))

        run = await orch.handle_message("sess1", "list files in workspace")
        await orch.wait_pending()

    loaded = await orch.get_run(run.run_id)
    assert loaded.status == RunStatus.COMPLETED
    assert loaded.clarification_rounds == 0
    # react_step was called (ReAct loop entered)
    mock_planner.react_step.assert_called()


@pytest.mark.asyncio
async def test_empty_questions_no_pause(setup):
    """Empty questions list → no pause even if confidence is low."""
    orch, settings, workspace = setup

    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(return_value=_mock_create_plan(
            confidence=0.1,  # very low
            questions=[],    # but no questions
        ))
        mock_planner.react_step = AsyncMock(return_value=_mock_react_final("Best effort."))

        run = await orch.handle_message("sess1", "vague request")
        await orch.wait_pending()

    loaded = await orch.get_run(run.run_id)
    assert loaded.status == RunStatus.COMPLETED
    mock_planner.react_step.assert_called()


@pytest.mark.asyncio
async def test_clarify_resumes_run(setup):
    """Submitting a clarification answer resumes the run to completion."""
    orch, settings, workspace = setup

    call_count = 0

    async def _create_plan_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: low confidence with questions
            return _mock_create_plan(
                confidence=0.3,
                questions=["Which file?"],
            )
        else:
            # Second call (after clarification): confident
            return _mock_create_plan(confidence=0.9, questions=[])

    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(side_effect=_create_plan_side_effect)
        mock_planner.react_step = AsyncMock(return_value=_mock_react_final("Done after clarification."))

        # Initial message → pauses
        run = await orch.handle_message("sess1", "read the file")
        await orch.wait_pending()

        loaded = await orch.get_run(run.run_id)
        assert loaded.status == RunStatus.AWAITING_CLARIFICATION

        # Submit clarification → resumes
        resumed = await orch.provide_clarification(run.run_id, "The README.md file")
        await orch.wait_pending()

    loaded = await orch.get_run(run.run_id)
    assert loaded.status == RunStatus.COMPLETED
    assert loaded.clarification_rounds == 1
    # The augmented message is used during processing but the DB preserves
    # the original user_message for audit purposes. Verify the run completed
    # after clarification by checking the final response.
    assert loaded.final_response == "Done after clarification."


@pytest.mark.asyncio
async def test_max_rounds_proceeds_best_effort(setup):
    """After clarification_max_rounds, proceeds best-effort without further pauses."""
    orch, settings, workspace = setup

    async def _always_ambiguous(*args, **kwargs):
        return _mock_create_plan(
            confidence=0.2,
            questions=["Still unclear?"],
        )

    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(side_effect=_always_ambiguous)
        mock_planner.react_step = AsyncMock(return_value=_mock_react_final("Best effort answer."))

        # Initial message → pauses (round 0)
        run = await orch.handle_message("sess1", "ambiguous thing")
        await orch.wait_pending()
        loaded = await orch.get_run(run.run_id)
        assert loaded.status == RunStatus.AWAITING_CLARIFICATION

        # Clarify round 1 → still ambiguous, pauses again (round 1)
        await orch.provide_clarification(run.run_id, "more info")
        await orch.wait_pending()
        loaded = await orch.get_run(run.run_id)
        assert loaded.status == RunStatus.AWAITING_CLARIFICATION
        assert loaded.clarification_rounds == 1

        # Clarify round 2 → max_rounds reached, proceeds best-effort
        await orch.provide_clarification(run.run_id, "even more info")
        await orch.wait_pending()

    loaded = await orch.get_run(run.run_id)
    # Should have completed (proceeded best-effort since rounds exhausted)
    assert loaded.status == RunStatus.COMPLETED
    assert loaded.clarification_rounds == 2


@pytest.mark.asyncio
async def test_child_run_never_pauses(setup):
    """Child/delegated runs skip the clarification gate entirely."""
    orch, settings, workspace = setup

    # Create a parent run first
    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(return_value=_mock_create_plan(
            confidence=0.9, questions=[],
        ))
        mock_planner.react_step = AsyncMock(return_value=_mock_react_final("parent done"))
        parent = await orch.handle_message("sess1", "parent task")
        await orch.wait_pending()

    # Now create a child run that would normally trigger clarification
    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(return_value=_mock_create_plan(
            confidence=0.1,
            questions=["Which one?"],
        ))
        mock_planner.react_step = AsyncMock(return_value=_mock_react_final("child done"))

        child = await orch.handle_child_message(
            parent_run_id=parent.run_id,
            task="child task",
            max_iterations=3,
        )

    assert child.status == RunStatus.COMPLETED
    assert child.clarification_rounds == 0
    # create_plan should still be called (for the confidence check)
    # but the gate should be skipped due to is_child=True
    mock_planner.react_step.assert_called()


@pytest.mark.asyncio
async def test_clarification_disabled(setup):
    """With clarification_enabled=False, behaves exactly as before."""
    orch, settings, workspace = setup

    # Override settings to disable clarification
    orch._settings = _make_settings(
        workspace.parent,
        clarification_enabled=False,
    )

    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(return_value=_mock_create_plan(
            confidence=0.1,
            questions=["Which file?"],
        ))
        mock_planner.react_step = AsyncMock(return_value=_mock_react_final("Done."))

        run = await orch.handle_message("sess1", "vague request")
        await orch.wait_pending()

    loaded = await orch.get_run(run.run_id)
    assert loaded.status == RunStatus.COMPLETED
    # create_plan should NOT even be called when clarification is disabled
    mock_planner.create_plan.assert_not_called()
    mock_planner.react_step.assert_called()


@pytest.mark.asyncio
async def test_provide_clarification_wrong_status_raises(setup):
    """Calling provide_clarification on a non-AWAITING_CLARIFICATION run raises."""
    orch, settings, workspace = setup

    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(return_value=_mock_create_plan(
            confidence=0.9, questions=[],
        ))
        mock_planner.react_step = AsyncMock(return_value=_mock_react_final("Done."))
        run = await orch.handle_message("sess1", "clear request")
        await orch.wait_pending()

    with pytest.raises(ValueError, match="not awaiting clarification"):
        await orch.provide_clarification(run.run_id, "answer")


@pytest.mark.asyncio
async def test_provide_clarification_missing_run_raises(setup):
    """Calling provide_clarification with a bad run_id raises."""
    orch, settings, workspace = setup
    with pytest.raises(ValueError, match="not found"):
        await orch.provide_clarification("run_doesnotexist", "answer")


@pytest.mark.asyncio
async def test_format_questions_single():
    """Single question formatting."""
    result = Orchestrator._format_questions(["Which directory?"])
    assert "Before I proceed" in result
    assert "Which directory?" in result


@pytest.mark.asyncio
async def test_format_questions_multiple():
    """Multiple questions formatting."""
    result = Orchestrator._format_questions(["Q1?", "Q2?", "Q3?"])
    assert "few questions" in result
    assert "1." in result
    assert "2." in result
    assert "3." in result


@pytest.mark.asyncio
async def test_clarification_fields_persist_in_db(setup):
    """Clarification fields round-trip through save/load correctly."""
    orch, settings, workspace = setup

    with patch.object(orch, "_planner") as mock_planner:
        mock_planner.create_plan = AsyncMock(return_value=_mock_create_plan(
            confidence=0.3,
            questions=["Question A?", "Question B?"],
        ))
        mock_planner.react_step = AsyncMock(side_effect=AssertionError("no"))

        run = await orch.handle_message("sess1", "ambiguous")
        await orch.wait_pending()

    loaded = await orch.get_run(run.run_id)
    assert loaded.clarifying_questions == ["Question A?", "Question B?"]
    assert loaded.clarification_rounds == 0
    assert loaded.status == RunStatus.AWAITING_CLARIFICATION
