"""
Mini-OpenClaw FastAPI application entry point.

Creates the app, configures CORS and logging, registers routes,
discovers tools, and initialises the database on startup.
"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import create_tables, get_connection
from .skills.registry import skill_registry
from .core.orchestrator import Orchestrator
from .core.scheduler import TaskScheduler
from .routes.health import router as health_router
from .routes.chat import router as chat_router
from .routes.runs import router as runs_router
from .routes.memory import router as memory_router
from .routes.tools import router as tools_router
from .routes.scheduler import router as scheduler_router

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle with full validation."""
    logger.info("Mini-OpenClaw starting up")

    # 1. Check that the selected LLM provider has a key configured
    provider_name = (settings.llm_provider or "anthropic").strip().lower()
    if not settings.active_provider_key:
        logger.warning(
            "LLM_PROVIDER=%s but no API key configured. Chat will return errors. "
            "Set the matching API key (ANTHROPIC_API_KEY or GEMINI_API_KEY) in .env.",
            provider_name,
        )
    else:
        logger.info(
            "LLM provider: %s (%s) — API key configured",
            provider_name,
            settings.active_provider_model,
        )

    # 2. Ensure workspace directory exists
    workspace = settings.resolved_workspace
    workspace.mkdir(parents=True, exist_ok=True)
    logger.info("Workspace root: %s", workspace)

    # 3. Create database tables
    try:
        await create_tables(settings.resolved_database)
        logger.info("Database ready: %s", settings.resolved_database)
    except Exception as exc:
        logger.error("Failed to initialise database: %s", exc)
        sys.exit(1)

    # 4. Discover and register tools (with MCP client if enabled)
    mcp_manager = None
    if settings.mcp_client_enabled and settings.mcp_servers:
        from .mcp.client import McpClientManager
        mcp_manager = McpClientManager(settings.mcp_servers)
        try:
            await mcp_manager.connect_all()
            logger.info(
                "MCP client: %d server(s) connected, %d remote tools discovered",
                mcp_manager.connected_server_count,
                len(mcp_manager.discovered_tools),
            )
        except Exception as exc:
            logger.warning("MCP client startup failed (non-fatal): %s", exc)
            mcp_manager = None
    elif settings.mcp_client_enabled:
        logger.info("MCP client enabled but no servers configured")

    skill_registry.discover(settings=settings, mcp_manager=mcp_manager)
    logger.info("Registered %d tools", skill_registry.tool_count)
    if mcp_manager:
        app.state.mcp_manager = mcp_manager

    # 5. Count existing memory items
    memory_count = 0
    try:
        conn = await get_connection(settings.resolved_database)
        try:
            rows = await conn.execute_fetchall(
                "SELECT COUNT(*) as cnt FROM memory_items"
            )
            memory_count = rows[0]["cnt"] if rows else 0
        finally:
            await conn.close()
    except Exception:
        pass

    # 6. Create orchestrator and attach to app state
    orchestrator = Orchestrator(settings, skill_registry)
    app.state.orchestrator = orchestrator

    # 7. Initialize memory vector store and reindex
    try:
        await orchestrator.initialize_memory()
    except Exception as exc:
        logger.warning("Memory initialization failed (non-fatal): %s", exc)

    tool_names = [t.manifest().name for t in skill_registry.list_tools()]
    logger.info(
        "Mini-OpenClaw ready: %d tools (%s), workspace at %s, memory: %d items",
        skill_registry.tool_count,
        ", ".join(tool_names),
        workspace,
        memory_count,
    )

    # 8. Start the task scheduler (if enabled)
    scheduler_task = None
    if settings.scheduler_enabled:
        scheduler = TaskScheduler(
            settings.resolved_database,
            orchestrator,
            max_tasks=settings.scheduler_max_tasks,
        )
        app.state.scheduler = scheduler
        orchestrator._scheduler = scheduler  # enables schedule_fn in ToolContext
        await scheduler.start()
        logger.info("Task scheduler enabled (max %d tasks)", settings.scheduler_max_tasks)
    else:
        logger.info("Task scheduler disabled")

    # 9. Mount MCP server (if enabled)
    if settings.mcp_server_enabled:
        try:
            from .mcp.server import McpServerBridge
            from starlette.routing import Mount, Route
            from starlette.requests import Request
            from starlette.responses import Response

            bridge = McpServerBridge(settings, skill_registry, orchestrator)
            app.state.mcp_server_bridge = bridge

            mcp_path = settings.mcp_server_path.rstrip("/")

            async def handle_sse(request: Request) -> Response:
                async with bridge.sse_transport.connect_sse(
                    request.scope, request.receive, request._send,
                ) as streams:
                    await bridge.mcp_server.run(
                        streams[0],
                        streams[1],
                        bridge.mcp_server.create_initialization_options(),
                    )
                return Response()

            # Mount SSE endpoint and POST message handler on the FastAPI app
            app.routes.append(Route(f"{mcp_path}/sse", endpoint=handle_sse, methods=["GET"]))
            app.routes.append(Mount(f"{mcp_path}/messages", app=bridge.sse_transport.handle_post_message))

            logger.info(
                "MCP server mounted at %s/sse (%d tool(s): %s)",
                mcp_path,
                len(bridge.exposed_tool_names),
                ", ".join(sorted(bridge.exposed_tool_names)) or "(none)",
            )
        except Exception as exc:
            logger.error("Failed to start MCP server (non-fatal): %s", exc, exc_info=True)
    yield

    # Shutdown
    if hasattr(app.state, "mcp_manager"):
        await app.state.mcp_manager.aclose_all()

    if settings.scheduler_enabled and hasattr(app.state, "scheduler"):
        await app.state.scheduler.stop()

    logger.info("Mini-OpenClaw shutting down")


app = FastAPI(
    title="Mini-OpenClaw",
    description="Lightweight local-first AI agent with auditable tool execution",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - allow the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{settings.frontend_port}",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routes
app.include_router(health_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(tools_router, prefix="/api")
app.include_router(scheduler_router, prefix="/api")
