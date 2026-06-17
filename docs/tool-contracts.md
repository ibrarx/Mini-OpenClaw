# Tool Contracts

Tools (skills) are registered through a manifest-driven registry so the agent can
gain capabilities without changing core orchestration logic. Each tool declares a
name, description, risk level, approval flag, and JSON input/output schemas; the
planner only ever sees registered tools, and adding one is a new module — no core
changes.

The authoritative contract for each tool is its manifest in
`apps/api/skills/<tool>.py` (validated by the tests in `tests/test_tools.py` and
`tests/test_new_tools.py`). This file summarizes the tool set and documents the
MCP proxy/exposure behavior in detail.

## Tool set (13 registered by default)

| Tool | Risk | Approval |
|------|------|----------|
| `list_files` | safe | no |
| `read_file` | safe | no |
| `search_in_files` | safe | no |
| `search_memory` | safe | no |
| `remember_fact` | safe | no |
| `get_datetime` | safe | no |
| `calculator` | safe | no |
| `system_info` | safe | no |
| `write_file` | medium | yes |
| `run_shell_safe` | medium/high | yes |
| `fetch_url` | high | yes |
| `delegate_task` | medium | yes |
| `schedule_task` | medium | yes (config) |

Plus two non-planner tools: `explain_run` (invoked via `GET /api/runs/{id}/explain`)
and `mcp_tool` (the dynamic proxy used for external MCP tools, below).

`delegate_task`, `schedule_task`, `fetch_url`, and MCP proxy tools are
registered conditionally based on `.env` flags and are excluded from child/
delegated runs.

## Structured result envelope

Every tool returns a normalized `ToolResult` (tool name, status, risk level,
input, output, error, timing, artifacts) so all executions are observable and
auditable.

## Adding a new tool

1. Create a module in `apps/api/skills/` implementing the `BaseTool` interface.
2. Define its manifest (name, schemas, risk level, approval flag).
3. The registry auto-discovers it at startup; the planner sees it automatically.
   No changes to orchestrator, policy, or executor.

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

**Approval semantics:** Tools with `approval_required=True` are listed for discovery but calls are refused with an MCP error when `MCP_SERVER_REQUIRE_APPROVAL=true` (default). When set to `false`, these tools execute immediately without human review — useful for trusted local testing but disables the safety gate for remote callers. `delegate_task` and `schedule_task` are hard-blocked from MCP exposure regardless of settings.

**Execution path:** MCP `call_tool` calls route through the same `Executor` and `PolicyEngine` used internally — path sandbox, command allowlist, and read-only mount enforcement all apply. A `ToolContext` is built via `Orchestrator.build_tool_context()` with a synthetic `mcp-<uuid>` run ID.
