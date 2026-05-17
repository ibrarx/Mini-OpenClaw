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
from .routes.health import router as health_router
from .routes.chat import router as chat_router
from .routes.runs import router as runs_router
from .routes.memory import router as memory_router
from .routes.tools import router as tools_router

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

    # 4. Discover and register tools
    skill_registry.discover(settings=settings)
    logger.info("Registered %d tools", skill_registry.tool_count)

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

    yield

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
