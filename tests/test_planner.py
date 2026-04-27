"""
Tests for the planner / router.

Uses mocked Claude API responses to test plan parsing, validation,
and error handling without requiring a live API key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.config import Settings
from apps.api.core.planner import Planner, PlannerError
from apps.api.models.run import Plan, TaskType
from apps.api.skills.registry import SkillRegistry


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def registry() -> SkillRegistry:
    return SkillRegistry()


@pytest.fixture
def settings() -> Settings:
    return Settings(anthropic_api_key="test-key-fake")


@pytest.fixture
def planner(settings: Settings, registry: SkillRegistry) -> Planner:
    return Planner(settings, registry)


def _mock_claude_response(text: str) -> MagicMock:
    """Build a mock Anthropic API response object."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ------------------------------------------------------------------
# Plan parsing
# ------------------------------------------------------------------


class TestPlanParsing:
    """Tests for Planner._parse_plan()."""

    def test_direct_answer_parsed(self, planner: Planner) -> None:
        raw = json.dumps({
            "task_type": "direct_answer",
            "confidence": 0.95,
            "reasoning": "A README is a documentation file.",
            "direct_answer": "A README is a documentation file.",
            "steps": [],
        })
        plan = planner._parse_plan(raw)
        assert plan.task_type == TaskType.DIRECT_ANSWER
        assert plan.confidence == 0.95
        assert "documentation" in plan.reasoning.lower()
        assert len(plan.steps) == 0

    def test_tool_needed_parsed(self, planner: Planner) -> None:
        raw = json.dumps({
            "task_type": "tool_needed",
            "confidence": 0.9,
            "reasoning": "User wants to list files.",
            "direct_answer": None,
            "steps": [
                {
                    "step_id": "step_1",
                    "tool": "list_files",
                    "args": {"path": "."},
                    "description": "List workspace files",
                }
            ],
        })
        plan = planner._parse_plan(raw)
        assert plan.task_type == TaskType.TOOL_NEEDED
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "list_files"
        assert plan.steps[0].args == {"path": "."}

    def test_multi_step_parsed(self, planner: Planner) -> None:
        raw = json.dumps({
            "task_type": "multi_step",
            "confidence": 0.85,
            "reasoning": "Read then write.",
            "direct_answer": None,
            "steps": [
                {"step_id": "step_1", "tool": "read_file", "args": {"path": "README.md"}},
                {"step_id": "step_2", "tool": "write_file", "args": {"path": "notes.txt", "content": "summary", "mode": "create"}},
            ],
        })
        plan = planner._parse_plan(raw)
        assert plan.task_type == TaskType.MULTI_STEP
        assert len(plan.steps) == 2

    def test_markdown_fences_stripped(self, planner: Planner) -> None:
        raw = '```json\n' + json.dumps({
            "task_type": "direct_answer",
            "confidence": 0.9,
            "reasoning": "test",
            "steps": [],
        }) + '\n```'
        plan = planner._parse_plan(raw)
        assert plan.task_type == TaskType.DIRECT_ANSWER

    def test_confidence_clamped(self, planner: Planner) -> None:
        raw = json.dumps({
            "task_type": "direct_answer",
            "confidence": 1.5,
            "reasoning": "test",
            "steps": [],
        })
        plan = planner._parse_plan(raw)
        assert plan.confidence == 1.0


# ------------------------------------------------------------------
# Plan validation
# ------------------------------------------------------------------


class TestPlanValidation:
    """Tests for Planner._validate_plan()."""

    def test_valid_tool_passes(self, planner: Planner) -> None:
        from apps.api.models.step import RunStep
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            reasoning="test",
            steps=[
                RunStep(step_id="s1", tool="list_files", args={"path": "."}),
                RunStep(step_id="s2", tool="read_file", args={"path": "x.txt"}),
            ],
        )
        # Should not raise
        planner._validate_plan(plan)

    def test_unknown_tool_raises(self, planner: Planner) -> None:
        from apps.api.models.step import RunStep
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            reasoning="test",
            steps=[RunStep(step_id="s1", tool="hack_the_planet", args={})],
        )
        with pytest.raises(ValueError, match="unknown tool"):
            planner._validate_plan(plan)


# ------------------------------------------------------------------
# Full planner flow (mocked Claude)
# ------------------------------------------------------------------


class TestPlannerFlow:
    """Integration tests with mocked Claude API."""

    @pytest.mark.asyncio
    async def test_direct_answer_flow(self, planner: Planner) -> None:
        mock_response = _mock_claude_response(json.dumps({
            "task_type": "direct_answer",
            "confidence": 0.95,
            "reasoning": "A README is a documentation file.",
            "direct_answer": "A README is a documentation file.",
            "steps": [],
        }))
        planner.client = MagicMock()
        planner.client.messages = MagicMock()
        planner.client.messages.create = AsyncMock(return_value=mock_response)

        plan = await planner.create_plan("What is a README file?")
        assert plan.task_type == TaskType.DIRECT_ANSWER
        assert len(plan.steps) == 0

    @pytest.mark.asyncio
    async def test_tool_routing_flow(self, planner: Planner) -> None:
        mock_response = _mock_claude_response(json.dumps({
            "task_type": "tool_needed",
            "confidence": 0.9,
            "reasoning": "User wants to list files.",
            "direct_answer": None,
            "steps": [
                {"step_id": "step_1", "tool": "list_files", "args": {"path": "."}, "description": "List files"},
            ],
        }))
        planner.client = MagicMock()
        planner.client.messages = MagicMock()
        planner.client.messages.create = AsyncMock(return_value=mock_response)

        plan = await planner.create_plan("List files in the workspace")
        assert plan.task_type == TaskType.TOOL_NEEDED
        assert plan.steps[0].tool == "list_files"

    @pytest.mark.asyncio
    async def test_invalid_json_retries(self, planner: Planner) -> None:
        """Planner should retry on invalid JSON, then raise PlannerError."""
        bad_response = _mock_claude_response("not json at all")
        planner.client = MagicMock()
        planner.client.messages = MagicMock()
        planner.client.messages.create = AsyncMock(return_value=bad_response)

        with pytest.raises(PlannerError, match="failed after"):
            await planner.create_plan("test")

    @pytest.mark.asyncio
    async def test_unknown_tool_in_plan_retries(self, planner: Planner) -> None:
        """Plan with unknown tool should cause retry and eventual failure."""
        bad_plan = _mock_claude_response(json.dumps({
            "task_type": "tool_needed",
            "confidence": 0.9,
            "reasoning": "test",
            "steps": [{"step_id": "step_1", "tool": "nonexistent_tool", "args": {}}],
        }))
        planner.client = MagicMock()
        planner.client.messages = MagicMock()
        planner.client.messages.create = AsyncMock(return_value=bad_plan)

        with pytest.raises(PlannerError):
            await planner.create_plan("test")
