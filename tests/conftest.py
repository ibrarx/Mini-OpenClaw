"""
Shared pytest fixtures for Mini-OpenClaw tests.

Provides temporary workspace directories, test database connections,
and common test helpers.
"""

import asyncio
from pathlib import Path

import pytest

from apps.api.database import create_tables


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
    # A text file
    readme = tmp_workspace / "README.md"
    readme.write_text("# Test Project\n\nThis is a test README.\n\nTODO: add more docs\n")

    # A subdirectory with files
    src = tmp_workspace / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello world')\n# TODO: implement\n")
    (src / "utils.py").write_text("def helper():\n    return 42\n")

    # Nested directory
    sub = src / "sub"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content\n")

    return tmp_workspace


@pytest.fixture
def db_ready(tmp_db_path: Path):
    """Create the database tables and return the path."""
    asyncio.get_event_loop().run_until_complete(create_tables(tmp_db_path))
    return tmp_db_path
