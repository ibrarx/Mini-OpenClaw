"""
Structured planner — Claude as a plan generator.

Converts user intent into a JSON plan referencing only registered
tools. The planner proposes; code decides.

Full Claude API integration in T04; this file provides the class
interface and a placeholder that returns a minimal plan.
"""

from __future__ import annotations

import logging
from typing import Any

from ..models.run import Plan, TaskType
from ..models.step import RunStep, RiskLevel
from ..models.tool_manifest import ToolManifest

logger = logging.getLogger(__name__)


class PlannerError(Exception):
    """Raised when plan generation fails."""


class Planner:
    """Generates structured JSON plans from user messages.

    Args:
        api_key: Anthropic API key.
        model: Model identifier (e.g. ``claude-sonnet-4-20250514``).
    """

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-20250514") -> None:
        self._api_key = api_key
        self._model = model

    async def create_plan(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        available_tools: list[ToolManifest] | None = None,
    ) -> Plan:
        """Ask Claude for a structured plan.

        Args:
            message: The user's natural-language request.
            context: Retrieved memory and conversation context.
            available_tools: Tool manifests the planner may reference.

        Returns:
            A validated Plan with steps referencing only registered tools.

        Raises:
            PlannerError: If the Claude API call fails after retries.
        """
        # Stub: returns a direct_answer plan.
        # Real implementation will call Claude API in T04.
        logger.info("Planner stub: treating message as direct_answer")
        return Plan(
            task_type=TaskType.DIRECT_ANSWER,
            confidence=0.5,
            reasoning="Stub planner — real implementation in T04.",
            steps=[],
        )
