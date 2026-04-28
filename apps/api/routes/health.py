"""Health check endpoint with full system diagnostics."""
import logging

from fastapi import APIRouter

from apps.api.config import get_settings
from apps.api.database import get_connection
from apps.api.skills.registry import skill_registry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    settings = get_settings()
    workspace = settings.resolved_workspace

    # Count memory items
    memory_count = 0
    db_status = "not_found"
    if settings.resolved_database.exists():
        db_status = "connected"
        try:
            conn = await get_connection(settings.resolved_database)
            try:
                rows = await conn.execute_fetchall(
                    "SELECT COUNT(*) as cnt FROM memory_items"
                )
                memory_count = rows[0]["cnt"] if rows else 0
            finally:
                await conn.close()
        except Exception as exc:
            db_status = f"error: {exc}"
            logger.warning("Health check DB error: %s", exc)

    tool_names = [t.manifest().name for t in skill_registry.list_tools()]

    return {
        "status": "ok",
        "api_key_configured": bool(settings.anthropic_api_key),
        "database": db_status,
        "tools_registered": skill_registry.tool_count,
        "tool_names": tool_names,
        "workspace_root": str(workspace),
        "workspace_exists": workspace.is_dir(),
        "memory_items_count": memory_count,
    }
