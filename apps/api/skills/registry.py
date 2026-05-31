"""skills/registry — Auto-discovers and registers all tools at startup."""
from __future__ import annotations
import logging
from typing import Any
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool
from apps.api.skills.list_files import ListFilesTool
from apps.api.skills.read_file import ReadFileTool
from apps.api.skills.write_file import WriteFileTool
from apps.api.skills.search_in_files import SearchInFilesTool
from apps.api.skills.run_shell_safe import RunShellSafeTool
from apps.api.skills.remember_fact import RememberFactTool
from apps.api.skills.search_memory import SearchMemoryTool
from apps.api.skills.delegate_task import DelegateTaskTool
from apps.api.skills.schedule_task import ScheduleTaskTool

logger = logging.getLogger(__name__)

_TOOL_CLASSES: list[type[BaseTool]] = [
    ListFilesTool, ReadFileTool, WriteFileTool, SearchInFilesTool,
    RunShellSafeTool, RememberFactTool, SearchMemoryTool,
]

# Delegation tool is registered separately — excluded in child runs
_DELEGATION_TOOL_CLASS: type[BaseTool] = DelegateTaskTool

# Scheduling tool is registered separately — excluded in child/scheduled runs
_SCHEDULE_TOOL_CLASS: type[BaseTool] = ScheduleTaskTool


class SkillRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def discover(self, settings=None, *, is_child_run: bool = False) -> None:
        for cls in _TOOL_CLASSES:
            # Skip memory-writing tools in child runs
            if is_child_run and cls in (RememberFactTool,):
                continue
            if cls is ReadFileTool and settings is not None:
                tool = ReadFileTool(
                    max_batch=settings.react_read_file_max_batch,
                    max_chars=settings.react_read_file_max_chars,
                )
            else:
                tool = cls()
            self._tools[tool.name] = tool
            logger.info("Registered tool: %s (risk=%s)", tool.name, tool.manifest().risk_level.value)

        # Register delegation tool only for top-level runs when enabled
        if not is_child_run and settings and getattr(settings, "delegate_enabled", True):
            dt = _DELEGATION_TOOL_CLASS(
                approval_required=getattr(settings, "delegate_approval_required", True),
            )
            self._tools[dt.name] = dt
            logger.info("Registered tool: %s (risk=%s, approval=%s)",
                        dt.name, dt.manifest().risk_level.value,
                        dt.manifest().approval_required)

        # Register scheduling tool only for top-level runs when enabled
        if not is_child_run and settings and getattr(settings, "scheduler_enabled", True):
            st = _SCHEDULE_TOOL_CLASS()
            self._tools[st.name] = st
            logger.info("Registered tool: %s (risk=%s, approval=%s)",
                        st.name, st.manifest().risk_level.value,
                        st.manifest().approval_required)

        logger.info("Tool discovery complete: %d tools", len(self._tools))

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def list_manifests(self) -> list[ToolManifest]:
        return [t.manifest() for t in self._tools.values()]

    def get_planner_descriptions(self) -> list[dict[str, Any]]:
        return [{"name": m.name, "description": m.description, "risk_level": m.risk_level.value,
                 "approval_required": m.approval_required, "input_schema": m.input_schema}
                for m in self.list_manifests()]

    @property
    def tool_count(self) -> int:
        return len(self._tools)


skill_registry = SkillRegistry()
