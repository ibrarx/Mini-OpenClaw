"""
Skill registry — discovers and manages tool modules.

At startup, ``discover()`` scans the skills package for BaseTool
subclasses, registers them, and makes their manifests available
to the planner, policy engine, and API routes.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Any

from ..models.tool_manifest import ToolManifest
from .base import BaseTool

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Registry of available tool implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, type[BaseTool]] = {}

    def register(self, tool_cls: type[BaseTool]) -> None:
        """Register a tool class by its manifest name.

        Args:
            tool_cls: A concrete BaseTool subclass.
        """
        manifest = tool_cls.get_manifest()
        name = manifest.name
        if name in self._tools:
            logger.warning("Tool %s already registered, overwriting", name)
        self._tools[name] = tool_cls
        logger.info("Registered tool: %s", name)

    def get_tool(self, name: str) -> type[BaseTool] | None:
        """Look up a tool class by name.

        Returns:
            The tool class, or None if not registered.
        """
        return self._tools.get(name)

    def get_all_manifests(self) -> list[ToolManifest]:
        """Return manifests for all registered tools.

        Returns:
            List of ToolManifest objects.
        """
        return [cls.get_manifest() for cls in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """Return a sorted list of registered tool names."""
        return sorted(self._tools.keys())

    def discover(self) -> None:
        """Auto-discover and register all BaseTool subclasses in the skills package.

        Scans every module in ``apps.api.skills`` for classes that
        inherit BaseTool and have a ``get_manifest`` classmethod.
        """
        import apps.api.skills as skills_package

        for importer, modname, ispkg in pkgutil.iter_modules(
            skills_package.__path__, prefix="apps.api.skills."
        ):
            if modname.endswith(".base") or modname.endswith(".registry"):
                continue
            try:
                module = importlib.import_module(modname)
            except Exception:
                logger.exception("Failed to import skill module: %s", modname)
                continue

            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, BaseTool)
                    and obj is not BaseTool
                    and not inspect.isabstract(obj)
                ):
                    try:
                        self.register(obj)
                    except Exception:
                        logger.exception("Failed to register tool from %s", modname)
