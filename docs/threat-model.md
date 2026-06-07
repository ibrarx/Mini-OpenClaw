# Threat Model
See project knowledge document 02-threat-model.md for full details.

## MCP Client Trust Boundary

External MCP servers are **untrusted** by default. They may advertise arbitrary tools, return malicious content, or hang indefinitely.

**Mitigations:**
- `MCP_CLIENT_ENABLED=false` by default — no MCP activity unless explicitly opted in.
- All MCP tools default to `RiskLevel.HIGH` and `approval_required=True` — they flow through the same approval gates and audit trail as native high-risk tools.
- Per-server `allowed_tools` allowlist restricts which remote tools are surfaced to the agent.
- Connection and call timeouts prevent a hung server from stalling a run.
- A failing MCP server is skipped at startup; it never crashes the agent or affects native tools.
- MCP tools are excluded from child/delegated runs to limit blast radius.
- MCP tools do not receive workspace-path privileges — they operate via the remote server, not via `resolve_tool_path`.
- All MCP tool executions are logged in the audit trail with full input/output.

## MCP Server Trust Boundary (Inbound)

When `MCP_SERVER_ENABLED=true`, Mini-OpenClaw accepts inbound tool calls from external MCP clients. These callers are **untrusted** — they may send malformed requests, attempt to access forbidden tools, or try to escape the workspace sandbox.

**Mitigations:**
- `MCP_SERVER_ENABLED=false` by default — no inbound MCP unless explicitly opted in.
- Default exposed set is safe, read-only tools only (`list_files`, `read_file`, `search_in_files`, `search_memory`). No mutating tools are exposed without explicit operator action.
- Approval-gated tools (write, shell, network, delegate, schedule) are refused with an MCP error by default. The operator must set `MCP_SERVER_REQUIRE_APPROVAL=false` AND add the tool to `MCP_SERVER_EXPOSED_TOOLS` to allow them — a loud warning is logged.
- `delegate_task` and `schedule_task` are never exposed over MCP (hard-coded block list).
- All MCP tool calls pass through the same `PolicyEngine` used internally: path sandbox, command allowlist, read-only mount enforcement all apply.
- Every MCP tool invocation produces audit records (`mcp_tool_called` / `mcp_tool_completed` / `mcp_tool_failed`) with a synthetic `mcp-<uuid>` run ID.
- 60-second timeout per tool call prevents a remote caller from tying up a worker.
- Malformed MCP requests return MCP-level errors; they never cause a 500 or destabilize the app.
- CORS configuration is not loosened for the MCP transport — it inherits the app's existing origins.
