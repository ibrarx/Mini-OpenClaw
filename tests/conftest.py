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
