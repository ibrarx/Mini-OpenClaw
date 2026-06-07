"""Health check endpoint with full system diagnostics."""
import logging

from fastapi import APIRouter, Request

from apps.api.config import get_settings
from apps.api.database import get_connection
from apps.api.skills.registry import skill_registry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request) -> dict:
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

    provider_name = (settings.llm_provider or "anthropic").strip().lower()
    api_key_configured = bool(settings.active_provider_key)
    api_key_status = (
        "local (no key needed)"
        if provider_name == "ollama"
        else ("configured" if api_key_configured else "missing")
    )
    # Mounts configuration
    mounts_info = [
        {
            "name": name,
            "path": str(path),
            "read_only": read_only,
            "exists": path.is_dir(),
        }
        for name, (path, read_only) in settings.resolved_mounts.items()
    ]

    # MCP server status
    mcp_server_info = None
    if settings.mcp_server_enabled:
        bridge = getattr(request.app.state, "mcp_server_bridge", None)
        exposed_tools: list[str] = []
        if bridge:
            exposed_tools = sorted(bridge.exposed_tool_names)
        else:
            from apps.api.mcp.server import _SAFE_DEFAULT_TOOLS
            if settings.mcp_server_exposed_tools:
                exposed_tools = sorted(settings.mcp_server_exposed_tools)
            else:
                exposed_tools = sorted(_SAFE_DEFAULT_TOOLS)
        mcp_server_info = {
            "enabled": True,
            "path": settings.mcp_server_path,
            "endpoint": f"{settings.mcp_server_path}/sse",
            "exposed_tools": exposed_tools,
            "require_approval": settings.mcp_server_require_approval,
        }

    return {
        "status": "ok",
        "llm_provider": provider_name,
        "llm_model": settings.active_provider_model,
        "api_key_configured": api_key_configured,
        "api_key_status": api_key_status,
        "anthropic_api_key_configured": bool(settings.anthropic_api_key),
        "gemini_api_key_configured": bool(settings.gemini_api_key),
        "database": db_status,
        "tools_registered": skill_registry.tool_count,
        "tool_names": tool_names,
        "workspace_root": str(workspace),
        "workspace_exists": workspace.is_dir(),
        "memory_items_count": memory_count,
        "mounts": mounts_info,
        "mcp_server": mcp_server_info,
    }
