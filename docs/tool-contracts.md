# Tool Contracts
See project knowledge document 03-tool-contracts.md for full details.

## MCP Proxy Tools

When `MCP_CLIENT_ENABLED=true`, the agent can consume tools from external MCP servers. Each remote tool is wrapped in an `McpProxyTool(BaseTool)` adapter and registered in the skill registry alongside native tools.

**Namespacing:** Remote tools are namespaced as `mcp__{server_name}__{tool_name}` (double underscore separator) to avoid collisions with native tools.

**Registration:** MCP proxy tools are registered during `SkillRegistry.discover()` after native tools. They appear in `get_planner_descriptions()` and are indistinguishable from native tools to the planner.

**Manifest:** Each proxy tool's manifest carries `RiskLevel.HIGH` by default, `approval_required` from the server config (default `True`), and the remote tool's advertised `input_schema` (passed through). The description is prefixed with `[MCP: {server_name}]`.

**Execution:** `McpProxyTool.execute()` calls the remote tool via `McpClientManager.call_tool()`, maps the MCP `CallToolResult` into a standard `ToolResult`, and classifies errors (timeout/connection → `TRANSIENT`, protocol/validation → `PERMANENT`). Exceptions never escape — always returns a `ToolResult`.

**Adding a new MCP server:** Add an entry to `MCP_SERVERS` in `.env` — no code changes needed. The proxy tools are auto-discovered and registered at startup.

## MCP Server — Exposing Tools over MCP

When `MCP_SERVER_ENABLED=true`, Mini-OpenClaw's own tools are surfaced over the Model Context Protocol so external clients can discover and call them.

**Manifest → MCP translation:** Each exposed tool's `ToolManifest` is translated into an MCP `Tool` definition: `name` stays identical, `description` is preserved as-is, and `input_schema` becomes the MCP `inputSchema`. The `name` is kept identical to the native tool name for clean round-tripping.

**Default exposed set:** `list_files`, `read_file`, `search_in_files`, `search_memory` — all `RiskLevel.SAFE` and non-mutating.

**Approval semantics:** Tools with `approval_required=True` are listed for discovery but calls are refused with an MCP error unless the operator disables the approval gate. `delegate_task` and `schedule_task` are hard-blocked from MCP exposure.

**Execution path:** MCP `call_tool` calls route through the same `Executor` and `PolicyEngine` used internally — path sandbox, command allowlist, and read-only mount enforcement all apply. A `ToolContext` is built via `Orchestrator.build_tool_context()` with a synthetic `mcp-<uuid>` run ID.
