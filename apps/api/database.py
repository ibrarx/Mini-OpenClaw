"""
Database setup and connection management for SQLite and Postgres.
"""

import logging
import os
from pathlib import Path
from typing import Any, AsyncGenerator

import aiosqlite
try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None

logger = logging.getLogger(__name__)

# SQL statements to create all tables.
# Note: Syntax is mostly compatible between SQLite and Postgres.
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
    role        TEXT NOT NULL,
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
    updated_at      TEXT NOT NULL
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
    memory_type   TEXT NOT NULL,
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


class DatabaseConnection:
    """A wrapper to unify SQLite and Postgres connection behavior."""
    def __init__(self, conn: Any, is_postgres: bool = False):
        self.conn = conn
        self.is_postgres = is_postgres

    async def execute(self, sql: str, params: tuple = ()) -> Any:
        sql = self._normalize_sql(sql)
        if self.is_postgres:
            return await self.conn.execute(sql, params)
        else:
            return await self.conn.execute(sql, params)

    async def execute_fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        sql = self._normalize_sql(sql)
        if self.is_postgres:
            async with self.conn.cursor() as cur:
                await cur.execute(sql, params)
                return await cur.fetchall()
        else:
            async with self.conn.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def commit(self):
        await self.conn.commit()

    async def close(self):
        await self.conn.close()

    def _normalize_sql(self, sql: str) -> str:
        if self.is_postgres:
            return sql.replace("?", "%s")
        return sql


async def get_connection(db_path: Path | str = "") -> DatabaseConnection:
    """Connect to SQLite or Postgres based on settings."""
    from .config import get_settings
    settings = get_settings()

    if settings.database_url:
        if not psycopg:
            raise ImportError("psycopg is required for Postgres support")
        logger.info("Connecting to Postgres database")
        conn = await psycopg.AsyncConnection.connect(
            settings.database_url,
            row_factory=dict_row,
            autocommit=True
        )
        return DatabaseConnection(conn, is_postgres=True)
    else:
        logger.info("Connecting to SQLite database at %s", db_path or settings.resolved_database)
        path = str(db_path) if db_path else str(settings.resolved_database)
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        return DatabaseConnection(conn, is_postgres=False)


async def create_tables(db_path: Path | str = "") -> None:
    """Initialise tables if they don't exist."""
    conn = await get_connection(db_path)
    try:
        # Postgres doesn't support executescript, so we split or handle differently
        for statement in CREATE_TABLES_SQL.split(";"):
            if statement.strip():
                await conn.execute(statement)
        await conn.commit()
    finally:
        await conn.close()


async def get_db() -> AsyncGenerator[DatabaseConnection, None]:
    """FastAPI dependency."""
    conn = await get_connection()
    try:
        yield conn
    finally:
        await conn.close()
