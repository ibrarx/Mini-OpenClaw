"""
Application settings loaded from environment variables and .env file.

Uses pydantic-settings for validation. All path settings use pathlib.Path
for cross-platform compatibility.

LLM provider selection
----------------------
Set ``LLM_PROVIDER`` to one of ``anthropic`` (default) or ``gemini`` to
choose which backend the planner uses. Each provider has its own
``<vendor>_api_key`` and ``<vendor>_model`` settings, all loaded from .env.
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

    # ----- LLM provider selection -----
    # Which backend the planner uses. Set in .env or the environment.
    # Allowed values: "anthropic" (default) or "gemini".
    llm_provider: str = "anthropic"

    # ----- Anthropic -----
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # ----- Gemini -----
    # GEMINI_API_KEY is read directly. The google-genai SDK also recognises
    # GOOGLE_API_KEY, but we keep the name explicit for clarity in our .env.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # ----- Paths — all use Path for cross-platform safety -----
    workspace_root: Path = Path("./workspace")
    database_path: Path = Path("./mini_openclaw.db")

    # ----- Server -----
    backend_port: int = 8000
    frontend_port: int = 5173
    log_level: str = "INFO"

    # ----- ReAct loop -----
    use_react: bool = True
    react_max_iterations: int = 10

    # ----- Memory summaries -----
    # How many completed runs between auto-generated conversation summaries.
    # Set to 0 to disable auto-summarization.
    summary_interval: int = 5
    # Maximum number of summaries to keep. Oldest are deleted when exceeded.
    max_summaries: int = 3

    # ----- Derived -----
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

    @property
    def active_provider_key(self) -> str:
        """Return the API key that the currently-selected provider will use.

        Used by ``/health`` and startup logging to report whether the active
        provider has credentials, without leaking the key itself.
        """
        provider = (self.llm_provider or "anthropic").strip().lower()
        if provider == "gemini":
            return self.gemini_api_key
        return self.anthropic_api_key

    @property
    def active_provider_model(self) -> str:
        """Return the model identifier the active provider will use."""
        provider = (self.llm_provider or "anthropic").strip().lower()
        if provider == "gemini":
            return self.gemini_model
        return self.anthropic_model


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
