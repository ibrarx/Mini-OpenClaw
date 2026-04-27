"""
Base class and shared types for all tools.

Every tool inherits BaseTool, implements ``execute()``, and provides
a ``get_manifest()`` class method so the registry can discover and
describe it without running tool code.
"""

from __future__ import annotations

import abc
from typing import Any

from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest


class BaseTool(abc.ABC):
    """Abstract base class for all Mini-OpenClaw tools.

    Subclasses must implement ``execute`` and ``get_manifest``.
    """

    @classmethod
    @abc.abstractmethod
    def get_manifest(cls) -> ToolManifest:
        """Return the declarative manifest describing this tool.

        The manifest is used by the planner (to know what tools exist),
        the policy engine (to check risk levels), and the UI (to show
        tool info).
        """
        ...

    @abc.abstractmethod
    async def execute(
        self, args: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        """Execute the tool with validated arguments.

        Args:
            args: Tool-specific arguments matching the input_schema.
            context: Runtime context including ``workspace_root``.

        Returns:
            Structured ToolResult envelope.
        """
        ...
