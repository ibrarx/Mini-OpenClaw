# CHANGES.md — Feedback and Changes Log

## Feedback Received During Poster Session

| # | Feedback | From | Action Taken | Rationale |
|---|----------|------|--------------|-----------|
| 1 | _"Consider adding..."_ | Peer reviewer | Implemented / Not implemented | _Reason_ |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |

## Changes Made After Poster Session

### Change 1: UI content updates — AI disclaimer, mount-aware examples, workspace helper
- **What changed:** Added an always-visible AI disclaimer below the chat input bar. Replaced the five hardcoded empty-state example commands with five workspace-centric base commands plus dynamically generated commands for each configured named mount (fetched from `/api/health`). Added a one-line workspace helper explaining what "the workspace" means. Widened the `healthCheck()` return type in the API client to include mount metadata.
- **Why:** Improve first-time user experience and clarify the agent's operating context. Mount-aware commands prevent "unknown mount alias" errors when mounts are not configured, and surface mount-specific commands when they are.
- **Files affected:** `apps/web/src/components/ChatPanel.tsx`, `apps/web/src/api/client.ts`, `apps/web/src/components/Settings.tsx`, `README.md`, `docs/demo-script.md`, `project_docs/project_status.md`, `CHANGES.md`

### Change 2: MCP client support — consume external MCP servers as tools
- **What changed:** Added the ability for Mini-OpenClaw to connect to external MCP (Model Context Protocol) servers and expose their tools to the agent as native tools. New modules: `apps/api/mcp/client.py` (connection lifecycle manager), `apps/api/skills/mcp_tool.py` (BaseTool proxy adapter). Configuration via `MCP_CLIENT_ENABLED` and `MCP_SERVERS` env vars. Tools namespaced as `mcp__{server}__{tool}`, defaulting to `RiskLevel.HIGH` with approval required. Graceful degradation on server failure. Off by default.
- **Why:** Extensibility — allows the agent to use third-party tool servers (filesystem, web, database, SaaS connectors) without writing a bespoke skill for each. Follows the manifest-driven tool extensibility philosophy.
- **Files affected:** `apps/api/mcp/__init__.py`, `apps/api/mcp/client.py`, `apps/api/skills/mcp_tool.py`, `apps/api/config.py`, `apps/api/skills/registry.py`, `apps/api/main.py`, `requirements.txt`, `.env.example`, `tests/test_mcp.py`, `README.md`, `CHANGES.md`, `docs/tool-contracts.md`, `docs/threat-model.md`, `docs/architecture.md`, `project_docs/project_status.md`

## Feedback Not Incorporated

| # | Feedback | Reason |
|---|----------|--------|
| 1 | | |
| 2 | | |
