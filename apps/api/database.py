"""
SQLite database setup, connection management, and table creation.

Uses aiosqlite for async access. Tables match the schema defined
in 04-memory-model.md and 01-architecture.md.
"""

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# SQL statements to create all tables.
# Order matters: no foreign-key dependencies in V1 (all TEXT references).
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    metadata    TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    run_id      TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    status          TEXT NOT NULL DEFAULT 'idle',
    user_message    TEXT NOT NULL,
    plan            TEXT,
    final_response  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    iterations      INTEGER NOT NULL DEFAULT 0,
    max_iterations  INTEGER NOT NULL DEFAULT 10,
    observations    TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS run_steps (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    step_index  INTEGER NOT NULL,
    tool        TEXT NOT NULL,
    args        TEXT NOT NULL DEFAULT '{}',
    risk_level  TEXT NOT NULL DEFAULT 'safe',
    status      TEXT NOT NULL DEFAULT 'pending',
    result      TEXT,
    error       TEXT,
    started_at  TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    step_id     TEXT NOT NULL,
    payload     TEXT NOT NULL,
    approved    INTEGER,
    decided_at  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id          TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    run_id      TEXT,
    step_id     TEXT,
    data        TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_items (
    id            TEXT PRIMARY KEY,
    workspace_id  TEXT NOT NULL DEFAULT 'default',
    memory_type   TEXT NOT NULL CHECK (memory_type IN ('fact', 'episode', 'summary')),
    content       TEXT NOT NULL,
    summary       TEXT,
    source        TEXT,
    confidence    REAL DEFAULT 0.5,
    visibility    TEXT NOT NULL DEFAULT 'user_visible',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    run_id        TEXT
);

CREATE TABLE IF NOT EXISTS tool_manifests (
    name              TEXT PRIMARY KEY,
    description       TEXT NOT NULL,
    risk_level        TEXT NOT NULL,
    approval_required INTEGER NOT NULL DEFAULT 0,
    input_schema      TEXT NOT NULL DEFAULT '{}',
    output_schema     TEXT NOT NULL DEFAULT '{}',
    registered_at     TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Migrations — add columns that may be missing from older databases.
# Each statement uses "ALTER TABLE … ADD COLUMN" which is a no-op error if
# the column already exists, so we catch and ignore that specific error.
# ---------------------------------------------------------------------------

MIGRATIONS = [
    "ALTER TABLE runs ADD COLUMN iterations INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE runs ADD COLUMN max_iterations INTEGER NOT NULL DEFAULT 10",
    "ALTER TABLE runs ADD COLUMN observations TEXT NOT NULL DEFAULT '[]'",
]


async def get_connection(db_path: Path) -> aiosqlite.Connection:
    """Open an async SQLite connection with WAL mode enabled."""
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def create_tables(db_path: Path) -> None:
    """Create all application tables if they don't exist, then run migrations."""
    logger.info("Creating database tables at %s", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await get_connection(db_path)
    try:
        await conn.executescript(CREATE_TABLES_SQL)
        await conn.commit()
        # Run migrations for existing databases that may lack newer columns.
        for stmt in MIGRATIONS:
            try:
                await conn.execute(stmt)
            except Exception:
                # Column already exists — expected for fresh or migrated DBs.
                pass
        await conn.commit()
        logger.info("Database tables created successfully")
    finally:
        await conn.close()


async def get_db() -> aiosqlite.Connection:
    """FastAPI dependency that yields an async SQLite connection.

    Usage in routes::

        @router.get("/example")
        async def example(db: aiosqlite.Connection = Depends(get_db)):
            ...

    The connection is opened at the start of the request and closed
    when the request finishes, even if an error occurs.
    """
    from .config import get_settings

    settings = get_settings()
    conn = await get_connection(settings.resolved_database)
    try:
        yield conn  # type: ignore[misc]
    finally:
        await conn.close()
