"""GET /api/tools — Return registered tool manifests."""
import logging

from fastapi import APIRouter

from apps.api.skills.registry import skill_registry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tools"])

@router.get("/tools")
async def list_tools() -> list[dict]:
    return [m.model_dump() for m in skill_registry.list_manifests()]
