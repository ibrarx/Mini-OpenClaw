"""Tests for the planner with mocked Claude API."""
import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from apps.api.core.planner import Planner, PlannerError
from apps.api.models.run import Plan, TaskType
from apps.api.models.step import RunStep
from apps.api.skills.registry import SkillRegistry

@pytest.fixture
def registry():
    r = SkillRegistry(); r.discover(); return r

@pytest.fixture
def planner(registry):
    return Planner(api_key="test-fake", model="test", registry=registry)

def _mock_response(text):
    cb = MagicMock(); cb.text = text
    r = MagicMock(); r.content = [cb]; return r

class TestParsing:
    def test_direct_answer(self, planner):
        p = planner._parse_plan(json.dumps({"task_type":"direct_answer","confidence":0.95,"reasoning":"A README is docs.","direct_answer":"A README is docs.","steps":[]}))
        assert p.task_type == TaskType.DIRECT_ANSWER and len(p.steps) == 0

    def test_tool_needed(self, planner):
        p = planner._parse_plan(json.dumps({"task_type":"tool_needed","confidence":0.9,"reasoning":"list","steps":[{"step_id":"s1","tool":"list_files","args":{"path":"."}}]}))
        assert p.task_type == TaskType.TOOL_NEEDED and p.steps[0].tool == "list_files"

    def test_markdown_fences(self, planner):
        raw = "```json\n" + json.dumps({"task_type":"direct_answer","confidence":0.9,"reasoning":"t","steps":[]}) + "\n```"
        assert planner._parse_plan(raw).task_type == TaskType.DIRECT_ANSWER

    def test_confidence_clamped(self, planner):
        p = planner._parse_plan(json.dumps({"task_type":"direct_answer","confidence":1.5,"reasoning":"t","steps":[]}))
        assert p.confidence == 1.0

class TestValidation:
    def test_valid_tool(self, planner):
        plan = Plan(task_type=TaskType.TOOL_NEEDED, confidence=0.9, steps=[RunStep(step_id="s1",tool="list_files",args={"path":"."})])
        planner._validate_plan(plan)  # should not raise

    def test_unknown_tool(self, planner):
        plan = Plan(task_type=TaskType.TOOL_NEEDED, confidence=0.9, steps=[RunStep(step_id="s1",tool="hack",args={})])
        with pytest.raises(ValueError, match="unknown tool"):
            planner._validate_plan(plan)

class TestFlow:
    @pytest.mark.asyncio
    async def test_direct_answer(self, planner):
        planner._client = MagicMock()
        planner._client.messages = MagicMock()
        planner._client.messages.create = AsyncMock(return_value=_mock_response(json.dumps({"task_type":"direct_answer","confidence":0.95,"reasoning":"A README.","direct_answer":"A README.","steps":[]})))
        plan = await planner.create_plan("What is a README?")
        assert plan.task_type == TaskType.DIRECT_ANSWER

    @pytest.mark.asyncio
    async def test_tool_routing(self, planner):
        planner._client = MagicMock()
        planner._client.messages = MagicMock()
        planner._client.messages.create = AsyncMock(return_value=_mock_response(json.dumps({"task_type":"tool_needed","confidence":0.9,"reasoning":"list","steps":[{"step_id":"s1","tool":"list_files","args":{"path":"."}}]})))
        plan = await planner.create_plan("List files")
        assert plan.steps[0].tool == "list_files"

    @pytest.mark.asyncio
    async def test_invalid_json_retries(self, planner):
        planner._client = MagicMock()
        planner._client.messages = MagicMock()
        planner._client.messages.create = AsyncMock(return_value=_mock_response("not json"))
        with pytest.raises(PlannerError):
            await planner.create_plan("test")
