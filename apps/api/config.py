"""
Application settings loaded from environment variables and .env file.

Uses pydantic-settings for validation. All path settings use pathlib.Path
for cross-platform compatibility.
"""

import tempfile
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Mini-OpenClaw configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Providers
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Paths — all use Path for cross-platform safety
    workspace_root: Path = Path("./workspace")
    # Database
    database_path: Path = Path("./mini_openclaw.db")
    database_url: str = ""  # If set, use Postgres (e.g. postgresql://user:pass@db/name)

    # Server
    backend_port: int = 8000
    frontend_port: int = 5173
    log_level: str = "INFO"

    # Derived
    @property
    def temp_dir(self) -> Path:
        return Path(tempfile.gettempdir())

    @property
    def resolved_workspace(self) -> Path:
        """Workspace root resolved to an absolute path."""
        return self.workspace_root.resolve()

    @property
    def resolved_database(self) -> Path:
        """Database path resolved to an absolute path."""
        return self.database_path.resolve()


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
