# CHANGES.md — Feedback and Changes Log

## Feedback Received During Poster Session

| # | Feedback | Scores (Problem/Solution) | Action Taken | Rationale |
|---|----------|--------------------------|--------------|-----------|
| 1 | "More testing to showcase all the tools they implemented." | 4/5 | Addressed in submission video | The screencast demonstrates all registered tools with live examples. No code change needed. |
| 2 | "Guys have ambitions to broaden this tool further and try to reduce the cost." | 5/5 | Acknowledged | Positive feedback. Cost optimization noted as future work. |
| 3 | "They talked a lot about the development process but not enough about what the project does. As an outsider, it was difficult to understand the capabilities." | 2/3 | **Poster revised** — rewrote the project intro to lead with concrete capability examples | This was the most critical feedback (lowest scores). The revised intro now answers "what can it do?" before explaining architecture. |
| 4 | "Reduce some of the text and make the most important points stand out more. Bigger fonts and more visual elements." | 4/4 | **Poster revised** — trimmed text in the abstract and the "what it delivers" blocks | Reduced wording per block and shortened item text for readability. |
| 5 | "Include more information about the testing setup and the types of tasks used to measure the agent's performance." | 4/4 | **Poster revised** — added an evaluation methodology summary | Now describes 14 deterministic tasks, 8 capability categories, sandboxed deterministic verification (no LLM-as-judge), and three configurations compared. |
| 6 | "Only a small improvement might be to broaden the tool coverage." | 5/5 | **Implemented** — added 3 new tools (get_datetime, calculator, system_info) | Low-effort, high-value additions that round out the tool suite. |
| 7 | "It's quite complete to me." | 5/5 | Acknowledged | Positive feedback — no change needed. |
| 8 | "It looks pretty complete to me already." | 5/5 | Acknowledged | Positive feedback — no change needed. |

## Changes Made After Poster Session

### Change 1: UI content updates — AI disclaimer, mount-aware examples, workspace helper
- **What changed:** Added an always-visible AI disclaimer below the chat input bar. Replaced the five hardcoded empty-state example commands with five workspace-centric base commands plus dynamically generated commands for each configured named mount (fetched from `/api/health`). Added a one-line workspace helper explaining what "the workspace" means. Widened the `healthCheck()` return type in the API client to include mount metadata.
- **Why:** Improve first-time user experience and clarify the agent's operating context. Mount-aware commands prevent "unknown mount alias" errors when mounts are not configured, and surface mount-specific commands when they are.
- **Files affected:** `apps/web/src/components/ChatPanel.tsx`, `apps/web/src/api/client.ts`, `apps/web/src/components/Settings.tsx`, `README.md`, `CHANGES.md`

### Change 2: MCP client support — consume external MCP servers as tools
- **What changed:** Added the ability for Mini-OpenClaw to connect to external MCP (Model Context Protocol) servers and expose their tools to the agent as native tools. New modules: `apps/api/mcp/client.py` (connection lifecycle manager), `apps/api/skills/mcp_tool.py` (BaseTool proxy adapter). Configuration via `MCP_CLIENT_ENABLED` and `MCP_SERVERS` env vars. Tools namespaced as `mcp__{server}__{tool}`, defaulting to `RiskLevel.HIGH` with approval required. Graceful degradation on server failure. Off by default.
- **Why:** Extensibility — allows the agent to use third-party tool servers (filesystem, web, database, SaaS connectors) without writing a bespoke skill for each. Follows the manifest-driven tool extensibility philosophy.
- **Files affected:** `apps/api/mcp/__init__.py`, `apps/api/mcp/client.py`, `apps/api/skills/mcp_tool.py`, `apps/api/config.py`, `apps/api/skills/registry.py`, `apps/api/main.py`, `requirements.txt`, `.env.example`, `tests/test_mcp.py`, `README.md`, `CHANGES.md`, `docs/tool-contracts.md`, `docs/threat-model.md`, `docs/architecture.md`

### Change 3: MCP server support — expose tools to external MCP clients
- **What changed:** Added the ability to expose Mini-OpenClaw's tools over MCP so external clients (e.g. Claude Desktop, other agents) can discover and call them via SSE transport. New module: `apps/api/mcp/server.py` (McpServerBridge). Configuration via `MCP_SERVER_ENABLED`, `MCP_SERVER_PATH`, `MCP_SERVER_EXPOSED_TOOLS`, `MCP_SERVER_REQUIRE_APPROVAL`. Default safe-only tool set (list_files, read_file, search_in_files, search_memory). Approval-gated tools refused by default (no human in the MCP loop). All calls routed through PolicyEngine and Executor; every invocation audited. Off by default.
- **Why:** Interoperability — allows Mini-OpenClaw to participate in the MCP ecosystem as a tool provider, not just a consumer. Useful for multi-agent workflows and Claude Desktop integration.
- **Files affected:** `apps/api/mcp/__init__.py`, `apps/api/mcp/server.py`, `apps/api/config.py`, `apps/api/core/orchestrator.py`, `apps/api/main.py`, `.env.example`, `tests/test_mcp_server.py`, `README.md`, `CHANGES.md`, `docs/api-spec.md`, `docs/threat-model.md`, `docs/tool-contracts.md`, `docs/architecture.md`

### Change 4: Three new tools — get_datetime, calculator, system_info (Feedback #6)
- **What changed:** Added three stateless utility tools: `get_datetime` (current time with IANA timezone support), `calculator` (safe math expression evaluation via AST walking — no `eval()`/`exec()`, attribute access disallowed), and `system_info` (CPU, memory, disk, platform, and uptime via psutil). All registered as `RiskLevel.SAFE` with no approval required, appended to `_TOOL_CLASSES` so they are always discovered. Added `psutil>=5.9.0` and `tzdata>=2024.1` to `requirements.txt` (`tzdata` ships the IANA database so timezone lookups work on platforms without a system tz DB, notably bare Windows).
- **Why:** Peer feedback suggested broadening tool coverage. These are low-effort, zero-risk additions that round out the agent's utility toolkit and demonstrate the manifest-driven extensibility.
- **Files affected:** `apps/api/skills/get_datetime.py`, `apps/api/skills/calculator.py`, `apps/api/skills/system_info.py`, `apps/api/skills/registry.py`, `requirements.txt`, `tests/test_new_tools.py`, `tests/test_tools.py`

### Change 5: Poster revisions (Feedback #3, #4, #5)
- **What changed:** (a) Rewrote the abstract to lead with concrete capability examples (organise/search files, edit documents, run shell commands, fetch web data, remember facts, schedule jobs, delegate sub-agents) before the architecture description. (b) Trimmed text in the abstract and the four "what it delivers" pillars for readability. (c) Added an evaluation methodology summary to the results panel: 14 deterministic tasks, 8 capability categories, sandboxed fixture workspace, deterministic verifiers (file contents, keyword presence, numeric answers) with no LLM-as-judge, and three configurations compared. (d) Updated the tool count to 13 built-in tools (the 10 registry tools + 3 new), with `explain_run` and MCP proxy tools shown separately.
- **Why:** The most critical feedback (scored 2/3) said outsiders couldn't understand what the project does. Additional feedback requested less text, more visual emphasis, and more evaluation detail.
- **Files affected:** `project_docs/Poster_Mini_OpenClaw_Group9.tex`
