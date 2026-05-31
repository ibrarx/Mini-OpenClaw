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
def _isolate_from_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent the local .env file from polluting test Settings.

    pydantic-settings reads .env from CWD automatically.  If a developer has
    e.g. LLM_PROVIDER=ollama in their .env, it overrides the code default
    inside the test suite, causing spurious failures.

    Environment variables take precedence over .env values in pydantic-settings,
    so we set the critical ones to their code defaults.  Individual tests that
    need a different provider pass it explicitly to Settings(...).
    """
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    # Set API keys to empty so the env var blocks any value in .env.
    # Using delenv would remove the env var entirely, letting .env leak through.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")


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

