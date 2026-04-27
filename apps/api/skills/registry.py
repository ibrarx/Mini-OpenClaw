"""
Skill registry — auto-discovers and registers tools at startup.

Each tool module in the skills/ package is imported, its BaseTool
subclass is instantiated, and the manifest is validated and stored.
Adding a new tool = adding a module — zero orchestrator changes.
"""

from __future__ import annotations

import logging
from typing import Any

from ..models.tool_manifest import ToolManifest
from .base import BaseTool
from .list_files import ListFilesTool
from .read_file import ReadFileTool
from .remember_fact import RememberFactTool
from .run_shell_safe import RunShellSafeTool
from .search_in_files import SearchInFilesTool
from .search_memory import SearchMemoryTool
from .write_file import WriteFileTool

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Central registry of available tools.

    Discovers and validates tool manifests at construction time.
    Provides lookup by name and bulk manifest listing.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._manifests: dict[str, ToolManifest] = {}
        self._discover()

    def _discover(self) -> None:
        """Instantiate all V1 tools and register them."""
        tool_classes: list[type[BaseTool]] = [
            ListFilesTool,
            ReadFileTool,
            WriteFileTool,
            SearchInFilesTool,
            RunShellSafeTool,
            RememberFactTool,
            SearchMemoryTool,
        ]

        for cls in tool_classes:
            try:
                instance = cls()
                manifest = instance.get_manifest()
                name = manifest.name

                if name in self._tools:
                    logger.warning(
                        "Duplicate tool name '%s' — skipping %s",
                        name,
                        cls.__name__,
                    )
                    continue

                self._tools[name] = instance
                self._manifests[name] = manifest
                logger.info(
                    "Registered tool: %s (risk=%s, approval=%s)",
                    name,
                    manifest.risk_level.value,
                    manifest.approval_required,
                )
            except Exception as exc:
                logger.error("Failed to register %s: %s", cls.__name__, exc)

        logger.info("Skill registry ready — %d tools registered", len(self._tools))

    def get_tool(self, name: str) -> BaseTool | None:
        """Look up a tool by canonical name."""
        return self._tools.get(name)

    def get_all_tools(self) -> dict[str, BaseTool]:
        """Return all registered tool instances."""
        return dict(self._tools)

    def get_all_manifests(self) -> list[ToolManifest]:
        """Return manifests for all registered tools."""
        return list(self._manifests.values())

    def get_manifest(self, name: str) -> ToolManifest | None:
        """Return the manifest for a specific tool."""
        return self._manifests.get(name)

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools
