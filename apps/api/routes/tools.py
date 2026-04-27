"""
GET /api/tools — Return registered tool manifests.

Lets the frontend and planner see which tools are available.
"""

from fastapi import APIRouter

from ..skills.registry import SkillRegistry

router = APIRouter(tags=["tools"])

# Singleton registry — created once at import time
_registry = SkillRegistry()


def get_registry() -> SkillRegistry:
    """Return the shared skill registry instance."""
    return _registry


@router.get("/tools")
async def list_tools() -> list[dict]:
    """Return manifests for all registered tools."""
    return [m.model_dump() for m in _registry.get_all_manifests()]
