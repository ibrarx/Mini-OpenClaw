# Threat Model

Mini-OpenClaw executes local tasks while minimizing the risks created by shell
access, local file access, stored credentials, and untrusted external content.
The security model is visible in the architecture: the LLM *proposes*, code
*decides*, and every action is policy-checked and audited.

For the full design rationale see the root [`README.md`](../README.md). This file
captures the core threat model plus the MCP trust boundaries in detail.

## Trust boundaries

1. **User input** — trusted as intent, never as validated executable instructions.
2. **LLM output** — advisory and structured, never inherently trusted.
3. **Tools** — can affect files/processes, so they require schema + policy validation.
4. **Workspace** — the agent operates only inside the configured root (and any read-only named mounts).
5. **External content** — files, web pages, MCP servers, and pasted text may carry prompt injection.

## Primary threats and mitigations

- **Prompt injection** — tool outputs and fetched content are treated as untrusted data, wrapped in delimited blocks, and can never redefine tools, policy, or approval state.
- **Shell abuse** — no arbitrary shell; only an allowlist (`pwd`, `ls`, `find`, `cat`, `grep`, translated per-OS), arguments parsed structurally, metacharacters blocked on all platforms.
- **Filesystem escape** — paths are canonicalized and confined to the workspace root; traversal (`../`) and tilde (`~`) expansion are denied; read/write scopes are separated.
- **Secret exposure** — credentials live in `.env`; known secret patterns are redacted from logs/UI; raw secrets are never stored in memory.
- **Over-trusting memory** — every memory item carries provenance, confidence, and visibility; items are inspectable and deletable; dream-inferred insights require explicit user review before they influence planning.
- **Approval bypass** — approval is enforced server-side, tied to the exact step payload, and invalidated if the payload changes; all approvals are audited.

## Risk classification

- **Safe** — read-only operations inside the workspace, low-risk memory lookups (auto-execute).
- **Approval-required** — file writes, shell commands, web fetch, delegation, scheduling.
- **Forbidden** — unrestricted shell, network exfiltration, credential dumping, OS process control, anything outside the workspace.

## Residual risk

This is a course proof-of-concept: controlled local demo use with explicit safety
boundaries, not an enterprise-hardened, fully autonomous system.

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
- Approval-gated tools (write, shell, network, delegate, schedule) are refused with an MCP error by default (`MCP_SERVER_REQUIRE_APPROVAL=true`). When set to `false`, these tools execute immediately without human review — the operator must also add them to `MCP_SERVER_EXPOSED_TOOLS`. A loud warning is logged at startup.
- `delegate_task` and `schedule_task` are never exposed over MCP (hard-coded block list).
- All MCP tool calls pass through the same `PolicyEngine` used internally: path sandbox, command allowlist, read-only mount enforcement all apply.
- Every MCP tool invocation produces audit records (`mcp_tool_called` / `mcp_tool_completed` / `mcp_tool_failed`) with a synthetic `mcp-<uuid>` run ID.
- 60-second timeout per tool call prevents a remote caller from tying up a worker.
- Malformed MCP requests return MCP-level errors; they never cause a 500 or destabilize the app.
- CORS configuration is not loosened for the MCP transport — it inherits the app's existing origins.
