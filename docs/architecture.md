# Architecture

Mini-OpenClaw is a local-first AI agent that turns natural-language requests into
safe, auditable tool executions. It runs as a local web app: a **React + TypeScript
(Vite)** frontend and a **Python FastAPI** backend, with **SQLite** for persistence
and **Server-Sent Events (SSE)** for live run updates.

For the complete narrative, screenshots, and evaluation data, see the root
[`README.md`](../README.md) and the poster in
[`project_docs/`](../project_docs/). This file documents the architecture at a
glance and the MCP integration in detail.

## Request lifecycle

Every request runs as a single auditable loop driven by the **orchestrator**
(`apps/api/core/orchestrator.py`):

```
User request
   → Planner        (LLMProvider proposes the next step as JSON)
   → Policy engine  (classifies: safe / approval-required / forbidden)
   → Executor       (runs the tool through the skill registry)
   → Observation    (result feeds back to the planner)
   ↺ continue / adapt / replan  — the hybrid Plan → ReAct → Replan loop
   → Final answer
```

Around the loop: the **memory manager** supplies context, the **audit logger**
records every decision, and SSE streams progress to the UI. The LLM only
*proposes*; code *decides* and *executes*.

## Core components (`apps/api/`)

- `core/orchestrator.py` — owns the run lifecycle (ReAct loop, replanning, approval waits)
- `core/planner.py` — builds prompts and parses structured plans; provider-agnostic
- `core/policy.py` — the security boundary (path sandbox, shell allowlist, injection checks)
- `core/executor.py` — invokes validated tools, captures timing/output/errors
- `core/audit.py` — append-only audit log
- `core/scheduler.py` — recurring/scheduled task runner
- `providers/` — pluggable `LLMProvider` interface with Anthropic, Gemini, and Ollama backends (see [provider-abstraction.md](provider-abstraction.md))
- `skills/` — manifest-driven tool registry (13 tools by default; see [tool-contracts.md](tool-contracts.md))
- `memory/` — five-layer memory with hybrid vector+keyword retrieval (see [memory-model.md](memory-model.md))
- `routes/` — FastAPI endpoints (see [api-spec.md](api-spec.md))

## Run state model

```
idle → planning → reacting → awaiting_approval → running → completed
                                              ↘ awaiting_clarification
                                              ↘ reflecting
                                              ↘ failed / cancelled
```

## Frontend (`apps/web/`)

React components for chat, plan preview, approval cards, live tool trace,
execution graph, run history, memory browser, and the scheduler page. The client
consumes the API contract only and subscribes to per-run SSE streams.

## MCP Client Support

The skill registry can optionally consume tools from external MCP (Model Context Protocol) servers. When `MCP_CLIENT_ENABLED=true`:

1. **Startup** (`main.py` lifespan): `McpClientManager` connects to each configured server via stdio, SSE, or streamable-HTTP transport, performs the MCP handshake, and discovers available tools.
2. **Registration** (`registry.py`): Each discovered remote tool is wrapped in an `McpProxyTool(BaseTool)` and registered in the skill registry. Tools are namespaced as `mcp__{server}__{tool}`.
3. **Execution**: MCP proxy tools execute through the standard `BaseTool` / executor path — no changes to the orchestrator or ReAct loop.
4. **Shutdown**: All MCP client connections are torn down cleanly.

The feature is off by default and has no effect on the agent when disabled.

## MCP Server Support

Mini-OpenClaw can expose its own tools over MCP so external clients can discover and call them. When `MCP_SERVER_ENABLED=true`:

1. **Startup** (`main.py` lifespan, step 9): `McpServerBridge` is created with access to the skill registry and orchestrator. It computes the exposed tool set and registers MCP `list_tools`/`call_tool` handlers.
2. **Transport**: An SSE-based MCP transport (`SseServerTransport`) is mounted on the FastAPI app at `MCP_SERVER_PATH` (default `/mcp`). Two routes are added: `GET /mcp/sse` (SSE stream) and `POST /mcp/messages/` (client messages).
3. **list_tools**: Returns MCP tool definitions translated from the exposed subset of `ToolManifest` entries in the skill registry.
4. **call_tool**: Routes through `Orchestrator.build_tool_context()` → `Executor.execute_tool()` — the same policy/audit pipeline used internally.
5. **Safety**: Default exposed set is safe, read-only tools only. Approval-gated tools are refused by default.

The feature is off by default and has no effect on the app when disabled.

### Route map addition
```
GET  /mcp/sse          → SSE stream for MCP client sessions
POST /mcp/messages/    → MCP client message handler
```
