"""
GET /api/tools — Return registered tool manifests.

Reads from the in-memory skill registry populated at startup.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from ..skills.registry import SkillRegistry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tools"])

# Module-level registry instance, populated during app startup.
_registry: SkillRegistry | None = None


def set_registry(registry: SkillRegistry) -> None:
    """Called during app startup to inject the registry."""
    global _registry
    _registry = registry


def get_registry() -> SkillRegistry:
    """Return the active skill registry."""
    if _registry is None:
        raise RuntimeError("Skill registry not initialised")
    return _registry


@router.get("/tools")
async def list_tools() -> list[dict[str, Any]]:
    """Return manifests for all registered tools."""
    registry = get_registry()
    return [m.model_dump() for m in registry.get_all_manifests()]
