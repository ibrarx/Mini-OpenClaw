"""
Application settings loaded from environment variables and .env file.

Uses pydantic-settings for validation. All path settings use pathlib.Path
for cross-platform compatibility.

LLM provider selection
----------------------
Set ``LLM_PROVIDER`` to one of ``anthropic`` (default) or ``gemini`` to
choose which backend the planner uses. Each provider has its own
``<vendor>_api_key`` and ``<vendor>_model`` settings, all loaded from .env.

Named mounts
-------------
Set ``WORKSPACE_MOUNTS`` to a JSON array to expose extra directories:

    WORKSPACE_MOUNTS='[{"name":"notes","path":"/home/me/notes","read_only":true}]'

Tools address them with a ``name:`` prefix, e.g. ``read_file("notes:todo.md")``.
Unprefixed paths resolve against the primary ``WORKSPACE_ROOT`` as before.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Named mount configuration ──────────────────────────────────

_MOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_RESERVED_NAMES = frozenset({"workspace", "system", "root", "self"})


class MountConfig(BaseModel):
    """A named secondary directory the agent can access."""
    name: str          # alias used in paths, e.g. "notes"
    path: Path         # absolute or relative directory
    read_only: bool = False


# ── MCP server configuration ──────────────────────────────────

_MCP_TRANSPORTS = frozenset({"stdio", "sse", "streamable_http"})


class McpServerConfig(BaseModel):
    """Configuration for one external MCP server the agent can connect to."""
    name: str                       # short alias, used to namespace tools
    transport: str                  # "stdio" | "sse" | "streamable_http"
    # stdio transport fields
    command: str = ""               # executable to launch (required for stdio)
    args: list[str] = []            # arguments for the subprocess
    # sse / streamable_http transport fields
    url: str = ""                   # server URL (required for sse/streamable_http)
    enabled: bool = True
    approval_required: bool = True  # default-on; per-server override
    allowed_tools: list[str] = []   # empty = all tools; non-empty = allowlist


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
    anthropic_model: str = "claude-sonnet-4-6"

    # ----- Gemini -----
    # GEMINI_API_KEY is read directly. The google-genai SDK also recognises
    # GOOGLE_API_KEY, but we keep the name explicit for clarity in our .env.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    # Vertex AI mode — use GCP credentials instead of API key.
    # Set VERTEX_AI=true + GCP_PROJECT + GCP_LOCATION in .env.
    # Auth: run `gcloud auth application-default login` first.
    vertex_ai: bool = False
    gcp_project: str = ""
    gcp_location: str = "us-central1"

    # ----- Ollama (local models) -----
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # ----- Paths — all use Path for cross-platform safety -----
    workspace_root: Path = Path("./workspace")
    database_path: Path = Path("./mini_openclaw.db")

    # Named mounts — JSON-encoded list of MountConfig objects from env.
    # Example: WORKSPACE_MOUNTS='[{"name":"notes","path":"/tmp/notes"}]'
    workspace_mounts: list[MountConfig] = []

    # ----- Server -----
    backend_port: int = 8000
    frontend_port: int = 5173
    log_level: str = "INFO"

    # ----- Clarification -----
    clarification_enabled: bool = True
    # If planner confidence is below this (or task_type == clarification_needed),
    # the agent asks clarifying questions before entering the ReAct loop.
    clarification_threshold: float = 0.5   # 0.0-1.0
    # Max clarification rounds before proceeding best-effort (prevents infinite loops).
    clarification_max_rounds: int = 2

    # ----- ReAct loop -----
    use_react: bool = True
    react_max_iterations: int = 10
    react_duplicate_cap: int = 3       # block after N identical tool+args calls
    react_use_goals: bool = False      # False = pure ReAct (no goals, no replanning)
    react_max_replans: int = 2         # 0 = goals but no replanning; >= 1 = full hybrid
    react_budget_warn_pct: int = 30    # warn LLM when this % of budget remains

    # Context window override (0 = auto-detect from model name)
    context_window_override: int = 0

    from pydantic import model_validator as _model_validator

    @_model_validator(mode="after")
    def _clamp_react_settings(self) -> "Settings":
        # Max iterations must be at least 1
        iters = max(1, self.react_max_iterations)
        object.__setattr__(self, "react_max_iterations", iters)
        # Duplicate cap must be at least 2 (1 would block on first retry)
        dup = max(2, self.react_duplicate_cap)
        object.__setattr__(self, "react_duplicate_cap", dup)
        # Replan cap: 0..5
        replans = max(0, min(5, self.react_max_replans))
        object.__setattr__(self, "react_max_replans", replans)
        # Budget warning percentage: 10..80
        pct = max(10, min(80, self.react_budget_warn_pct))
        object.__setattr__(self, "react_budget_warn_pct", pct)

        # Clarification threshold: 0.0..1.0
        thresh = max(0.0, min(1.0, self.clarification_threshold))
        object.__setattr__(self, "clarification_threshold", thresh)
        # Clarification max rounds: 0..5
        clar_rounds = max(0, min(5, self.clarification_max_rounds))
        object.__setattr__(self, "clarification_max_rounds", clar_rounds)

        # Validate workspace mount names
        seen: set[str] = set()
        for mount in self.workspace_mounts:
            name = mount.name
            if not name or not _MOUNT_NAME_RE.match(name):
                raise ValueError(
                    f"Mount name must be non-empty, alphanumeric/underscore only: {name!r}"
                )
            if name.lower() in _RESERVED_NAMES:
                raise ValueError(
                    f"Mount name {name!r} is reserved (cannot use: {', '.join(sorted(_RESERVED_NAMES))})"
                )
            if name in seen:
                raise ValueError(f"Duplicate mount name: {name!r}")
            seen.add(name)

        # Validate MCP server configs
        mcp_seen: set[str] = set()
        for srv in self.mcp_servers:
            name = srv.name
            if not name or not _MOUNT_NAME_RE.match(name):
                raise ValueError(
                    f"MCP server name must be non-empty, alphanumeric/underscore only: {name!r}"
                )
            if name.lower() in _RESERVED_NAMES:
                raise ValueError(
                    f"MCP server name {name!r} is reserved (cannot use: {', '.join(sorted(_RESERVED_NAMES))})"
                )
            if name in mcp_seen:
                raise ValueError(f"Duplicate MCP server name: {name!r}")
            mcp_seen.add(name)

            transport = srv.transport.lower()
            if transport not in _MCP_TRANSPORTS:
                raise ValueError(
                    f"MCP server {name!r}: transport must be one of "
                    f"{', '.join(sorted(_MCP_TRANSPORTS))}, got {srv.transport!r}"
                )
            if transport == "stdio":
                if not srv.command:
                    raise ValueError(
                        f"MCP server {name!r}: 'command' is required for stdio transport"
                    )
            elif transport in ("sse", "streamable_http"):
                if not srv.url:
                    raise ValueError(
                        f"MCP server {name!r}: 'url' is required for {transport} transport"
                    )

        # Validate MCP server path prefix
        mcp_path = self.mcp_server_path
        if not mcp_path.startswith("/"):
            object.__setattr__(self, "mcp_server_path", "/" + mcp_path)

        return self

    # ----- Tool limits -----
    react_read_file_max_batch: int = 10     # max files per batch read_file call
    react_read_file_max_chars: int = 50000  # max total output chars per read_file call

    # Max characters kept per tool observation when fed back to the planner.
    # Applies to all tools except read_file (which has its own limits below).
    # Increase if the planner is missing data from search_in_files, run_shell_safe, etc.
    react_observation_max_chars: int = 1000

    # Max characters kept per read_file observation when fed back to the planner.
    # Single = one file read; batch = per-file limit in a multi-file read.
    react_read_file_obs_single: int = 3000
    react_read_file_obs_batch: int = 2000

    # ----- Self-reflection -----
    # Critique the agent's final answer before delivering it to the user.
    # When the score is below threshold and iteration budget remains, the agent
    # re-enters the ReAct loop to take corrective action. If no budget remains,
    # falls back to a text-only rewrite.
    react_self_reflect: bool = False         # master toggle
    react_reflect_quality_threshold: float = 0.7  # 0.0-1.0, below this triggers loop re-entry

    # ----- Memory summaries -----
    # How many completed runs between auto-generated conversation summaries.
    # Set to 0 to disable auto-summarization.
    summary_interval: int = 5
    # Maximum number of summaries to keep. Oldest are deleted when exceeded.
    max_summaries: int = 3

    # ----- Agent Dreams (memory consolidation) -----
    # Dream every N episodes (0 = disabled). Dreams mine episodes for
    # strategies and preferences, proposing them for user review.
    dream_interval: int = 5
    # Max active strategies and preferences to keep. When at cap, the
    # lowest-confidence item is evicted if a new insight scores higher.
    dream_max_strategies: int = 10
    dream_max_preferences: int = 10
    # Minimum confidence threshold for dream-generated insights.
    dream_confidence_threshold: float = 0.6

    # ----- Sub-agent delegation -----
    delegate_enabled: bool = True
    delegate_approval_required: bool = True  # require user approval before spawning child
    delegate_max_depth: int = 2            # max nesting level (0=parent only)
    delegate_max_children: int = 3         # max child runs per parent
    delegate_max_child_iterations: int = 5 # iteration cap per child

    # ----- Task scheduler -----
    scheduler_enabled: bool = True
    scheduler_max_tasks: int = 20         # max active scheduled tasks

    # ----- Web fetch -----
    # Runtime URL fetching for live data (weather, APIs, docs).
    # EMPTY allowlist = block everything (opt-in by design).
    # Add domains to the allowlist to enable, e.g. ["api.open-meteo.com"].
    # Subdomains of an allowed domain are permitted automatically.
    web_fetch_enabled: bool = True
    web_fetch_allowed_domains: list[str] = []
    web_fetch_max_bytes: int = 1_048_576      # 1 MB response cap
    web_fetch_timeout_seconds: float = 10.0
    web_fetch_max_redirects: int = 3

    # ----- MCP client -----
    # Connect to external MCP servers and expose their tools to the agent.
    # OFF by default — enable to consume third-party tool servers.
    mcp_client_enabled: bool = False
    # JSON-encoded list of McpServerConfig objects.
    # Example: MCP_SERVERS='[{"name":"fs","transport":"stdio","command":"npx","args":["-y","@anthropic/mcp-filesystem"]}]'
    mcp_servers: list[McpServerConfig] = []

    # ----- MCP server (expose tools TO external clients) -----
    # OFF by default — enable to let external MCP clients (e.g. Claude Desktop)
    # discover and call Mini-OpenClaw tools over MCP.
    mcp_server_enabled: bool = False
    # Route prefix where the MCP SSE transport is mounted on the FastAPI app.
    mcp_server_path: str = "/mcp"
    # Allowlist of tool names to expose. Empty = safe default set only
    # (list_files, read_file, search_in_files, search_memory).
    mcp_server_exposed_tools: list[str] = []
    # Whether approval-gated tools can be executed by remote MCP callers.
    # True (default) = refuse with error; False = allow (requires explicit allowlist).
    mcp_server_require_approval: bool = True

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
    def resolved_mounts(self) -> dict[str, tuple[Path, bool]]:
        """alias -> (resolved_absolute_path, read_only)."""
        out: dict[str, tuple[Path, bool]] = {}
        for m in self.workspace_mounts:
            out[m.name] = (m.path.resolve(), m.read_only)
        return out

    @property
    def active_provider_key(self) -> str:
        """Return the API key that the currently-selected provider will use.

        Used by ``/health`` and startup logging to report whether the active
        provider has credentials, without leaking the key itself.
        Ollama runs locally and needs no key — returns ``"local"`` as a
        sentinel value that always evaluates to truthy.
        """
        provider = (self.llm_provider or "anthropic").strip().lower()
        if provider == "ollama":
            return "local"
        if provider == "gemini":
            return self.gemini_api_key
        return self.anthropic_api_key

    @property
    def active_provider_model(self) -> str:
        """Return the model identifier the active provider will use."""
        provider = (self.llm_provider or "anthropic").strip().lower()
        if provider == "ollama":
            return self.ollama_model
        if provider == "gemini":
            return self.gemini_model
        return self.anthropic_model


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
