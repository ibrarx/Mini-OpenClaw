"""
Mini-OpenClaw FastAPI application entry point.

Creates the app, configures CORS and logging, registers routes,
discovers tools, and initialises the database on startup.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import create_tables
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
    """Startup and shutdown lifecycle."""
    logger.info("Mini-OpenClaw starting up")

    # Ensure workspace directory exists
    workspace = settings.resolved_workspace
    workspace.mkdir(parents=True, exist_ok=True)
    logger.info("Workspace root: %s", workspace)

    # Create database tables
    await create_tables(settings.resolved_database)
    logger.info("Database ready: %s", settings.resolved_database)

    # Discover and register tools
    skill_registry.discover()

    # Create orchestrator and attach to app state
    orchestrator = Orchestrator(settings, skill_registry)
    app.state.orchestrator = orchestrator
    logger.info("Orchestrator ready with %d tools", skill_registry.tool_count)

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
