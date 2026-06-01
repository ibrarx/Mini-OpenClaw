"""
Shared pytest fixtures for Mini-OpenClaw tests.

Provides temporary workspace directories, test database paths,
and common test helpers.
"""

import os
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from apps.api.database import create_tables, get_connection
from apps.api.skills.base import ToolContext


@pytest.fixture(autouse=True)
def _isolate_from_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent the local .env file from polluting test Settings.

    pydantic-settings reads .env from CWD automatically.  If a developer has
    e.g. GEMINI_API_KEY=xxx in their .env, it can leak into Settings() because
    pydantic cannot distinguish ``Settings(field="")`` from ``Settings()``
    when the default is also ``""``, so the init kwarg doesn't reliably
    override the .env value.

    Fix: chdir to a temp directory that has no .env file, then also set
    critical env vars to safe defaults.  monkeypatch restores the original
    CWD after each test automatically.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    # Disable clarification by default in tests so existing tests that mock
    # react_step aren't surprised by an extra create_plan call.
    monkeypatch.setenv("CLARIFICATION_ENABLED", "false")


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory for testing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a path for a temporary test database."""
    return tmp_path / "test.db"


@pytest.fixture
def populated_workspace(tmp_workspace: Path) -> Path:
    """Create a workspace with sample files for tool testing."""
    readme = tmp_workspace / "README.md"
    readme.write_text("# Test Project\n\nThis is a test README.\n\nTODO: add more docs\n")
    src = tmp_workspace / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello world')\n# TODO: implement\n")
    (src / "utils.py").write_text("def helper():\n    return 42\n")
    sub = src / "sub"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content\n")
    return tmp_workspace


def make_tool_context(workspace: Path, db_path: Path | None = None) -> ToolContext:
    """Create a ToolContext for testing."""
    return ToolContext(
        workspace_root=str(workspace),
        run_id="test_run",
        step_id="test_step",
        db_path=str(db_path) if db_path else "",
    )

