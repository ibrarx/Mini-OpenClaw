"""Health check endpoint."""
from fastapi import APIRouter
from apps.api.config import get_settings
from apps.api.skills.registry import skill_registry

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "tool_count": skill_registry.tool_count,
        "database": "connected" if settings.resolved_database.exists() else "not_found",
        "api_key_configured": bool(settings.anthropic_api_key),
        "workspace": str(settings.resolved_workspace),
    }
