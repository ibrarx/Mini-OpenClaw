"""
Shared pytest fixtures for Mini-OpenClaw tests.

Provides temporary workspace directories, test database connections,
and common test helpers.
"""

from pathlib import Path

import pytest


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
