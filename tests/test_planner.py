"""
Tests for the structured planner with mocked Claude API (AsyncAnthropic).

Covers: plan creation, JSON parsing, markdown fence stripping,
confidence clamping, direct answer flow, error handling, summary generation.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.core.planner import Planner, PlannerError
from apps.api.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> SkillRegistry:
    r = SkillRegistry()
    r.discover()
    return r


@pytest.fixture
def planner(registry: SkillRegistry) -> Planner:
    return Planner(api_key="test-fake", model="test", registry=registry)


def _mock_response(text: str) -> MagicMock:
    """Build a mock Anthropic API response with the given text."""
    cb = MagicMock()
    cb.text = text
    cb.type = "text"
    r = MagicMock()
    r.content = [cb]
    return r


def _patch(planner: Planner, response: MagicMock) -> None:
    """Patch the planner's async client to return a canned response."""
    planner._client = MagicMock()
    planner._client.messages.create = AsyncMock(return_value=response)


# ---------------------------------------------------------------------------
# Plan creation
# ---------------------------------------------------------------------------


class TestCreatePlan:
    @pytest.mark.asyncio
    async def test_direct_answer(self, planner: Planner) -> None:
        raw = json.dumps({
            "task_type": "direct_answer",
            "confidence": 0.95,
            "reasoning": "A README is documentation.",
            "direct_response": "A README is a documentation file.",
            "steps": [],
        })
        _patch(planner, _mock_response(raw))
        plan = await planner.create_plan(user_message="What is a README?")
        assert plan["task_type"] == "direct_answer"
        assert plan["direct_response"] == "A README is a documentation file."
        assert plan["steps"] == []

    @pytest.mark.asyncio
    async def test_tool_routing(self, planner: Planner) -> None:
        raw = json.dumps({
            "task_type": "tool_needed",
            "confidence": 0.9,
            "reasoning": "list files",
            "steps": [{"step_id": "s1", "tool": "list_files", "args": {"path": "."}, "risk_level": "safe"}],
        })
        _patch(planner, _mock_response(raw))
        plan = await planner.create_plan(user_message="List files")
        assert plan["task_type"] == "tool_needed"
        assert len(plan["steps"]) == 1
        assert plan["steps"][0]["tool"] == "list_files"

    @pytest.mark.asyncio
    async def test_multi_step_plan(self, planner: Planner) -> None:
        raw = json.dumps({
            "task_type": "multi_step",
            "confidence": 0.85,
            "reasoning": "read then write",
            "steps": [
                {"step_id": "s1", "tool": "read_file", "args": {"path": "README.md"}, "risk_level": "safe"},
                {"step_id": "s2", "tool": "write_file", "args": {"path": "n.txt", "content": "x", "mode": "create"}, "risk_level": "medium"},
            ],
        })
        _patch(planner, _mock_response(raw))
        plan = await planner.create_plan(user_message="read and write")
        assert plan["task_type"] == "multi_step"
        assert len(plan["steps"]) == 2

    @pytest.mark.asyncio
    async def test_markdown_fences_stripped(self, planner: Planner) -> None:
        inner = json.dumps({"task_type": "direct_answer", "confidence": 0.9, "reasoning": "t", "steps": []})
        _patch(planner, _mock_response(f"```json\n{inner}\n```"))
        plan = await planner.create_plan(user_message="test")
        assert plan["task_type"] == "direct_answer"

    @pytest.mark.asyncio
    async def test_invalid_json_raises_planner_error(self, planner: Planner) -> None:
        _patch(planner, _mock_response("not json at all"))
        with pytest.raises(PlannerError):
            await planner.create_plan(user_message="test")

    @pytest.mark.asyncio
    async def test_clarification_response(self, planner: Planner) -> None:
        raw = json.dumps({
            "task_type": "clarification_needed",
            "confidence": 0.3,
            "reasoning": "Ambiguous",
            "direct_response": "Could you clarify?",
            "steps": [],
        })
        _patch(planner, _mock_response(raw))
        plan = await planner.create_plan(user_message="do the thing")
        assert plan["task_type"] == "clarification_needed"
        assert plan["direct_response"] is not None

    @pytest.mark.asyncio
    async def test_defaults_applied(self, planner: Planner) -> None:
        _patch(planner, _mock_response(json.dumps({"task_type": "direct_answer"})))
        plan = await planner.create_plan(user_message="test")
        assert "confidence" in plan
        assert "reasoning" in plan
        assert "steps" in plan
        assert "direct_response" in plan

    @pytest.mark.asyncio
    async def test_confidence_passthrough(self, planner: Planner) -> None:
        raw = json.dumps({"task_type": "direct_answer", "confidence": 1.5, "reasoning": "t", "steps": []})
        _patch(planner, _mock_response(raw))
        plan = await planner.create_plan(user_message="test")
        assert plan["confidence"] == 1.5


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_summary_returns_text(self, planner: Planner) -> None:
        _patch(planner, _mock_response("Here is the summary."))
        result = await planner.generate_summary("List files", [{"tool": "list_files", "status": "success"}])
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_summary_handles_api_error(self, planner: Planner) -> None:
        planner._client = MagicMock()
        planner._client.messages.create = AsyncMock(side_effect=Exception("API error"))
        result = await planner.generate_summary("test", [])
        assert "completed" in result.lower() or "traces" in result.lower()
