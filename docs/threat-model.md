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
