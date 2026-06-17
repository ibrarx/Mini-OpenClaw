# API Specification

FastAPI backend on `localhost:8000`, JSON over HTTP, with per-run **Server-Sent
Events** for live updates. All application routes are mounted under `/api`.
Local demo mode (minimal session-based access).

The route handlers in `apps/api/routes/` are the source of truth. This file lists
the current endpoints and documents the MCP server transport in detail.

## Endpoints (prefix `/api`)

**Chat & runs**
- `POST /chat` — submit a message, create a run
- `POST /chat/retry/{run_id}` — retry a failed run
- `GET /runs` — list runs (filters: session, workspace, status, limit, offset)
- `GET /runs/{run_id}` — run status, steps, approvals, outputs
- `GET /runs/{run_id}/stream` — SSE stream of run events
- `GET /runs/{run_id}/explain` — natural-language explanation of a run (`detail_level`)
- `POST /runs/{run_id}/approve` — approve a pending step
- `POST /runs/{run_id}/cancel` — cancel an active run
- `POST /runs/{run_id}/clarify` — answer a clarification prompt

**Memory**
- `GET /memory` — list memory items (filters: workspace, type, query, limit)
- `POST /memory/search` — keyword/hybrid retrieval
- `GET /memory/export` — export all memory as formatted JSON
- `GET /memory/pending` — dream-proposed insights awaiting review
- `POST /memory/{item_id}/review` — approve/reject a proposed insight
- `POST /memory/dream` — trigger a memory-consolidation (dream) cycle
- `DELETE /memory/{item_id}` — delete a memory item

**Scheduler**
- `GET /scheduler/health`, `GET /tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/runs`
- `POST /tasks/{id}/pause`, `POST /tasks/{id}/resume`, `DELETE /tasks/{id}`

**Tools / usage / settings / health**
- `GET /tools` — registered tool manifests
- `GET /usage/summary` — token/cost usage summary
- `GET /settings/clarification`, `PATCH /settings/clarification`
- `GET /health` — diagnostics (active provider/model, API key status, tool count, DB, workspace, memory count)

## Event types (SSE / polling)

`run_created`, `planning_started`, `plan_ready`, `approval_requested`,
`step_started`, `step_completed`, `step_failed`, `memory_written`,
`run_completed`, `run_failed`.

## Error model

```json
{ "error": { "code": "POLICY_DENIED", "message": "Command not allowed by shell policy.", "details": { "command": "rm" } } }
```

## MCP Server Transport

When `MCP_SERVER_ENABLED=true`, an SSE-based MCP transport is mounted on the FastAPI app:

### GET /mcp/sse
Establishes a Server-Sent Events stream for an MCP client session. The client receives MCP messages (tool results, errors) over this stream.

### POST /mcp/messages/
Receives MCP client messages (list_tools, call_tool requests) and routes them to the MCP server. Each POST must include a session ID linking it to an active SSE connection.

### MCP Protocol Operations

- **list_tools**: Returns tool definitions for the exposed tool set. Each definition includes `name`, `description`, and `inputSchema` matching the native tool manifest's `input_schema`.
- **call_tool(name, arguments)**: Executes the named tool through the same policy/executor pipeline used internally. Returns structured JSON output on success, or an error object with a `code` field (`TOOL_NOT_EXPOSED`, `APPROVAL_REQUIRED`, `TOOL_ERROR`, `TIMEOUT`, `INTERNAL_ERROR`).

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SERVER_ENABLED` | `false` | Mount the MCP transport |
| `MCP_SERVER_PATH` | `/mcp` | Route prefix |
| `MCP_SERVER_EXPOSED_TOOLS` | `[]` | Allowlist (empty = safe defaults) |
| `MCP_SERVER_REQUIRE_APPROVAL` | `true` | Refuse approval-gated tools |
