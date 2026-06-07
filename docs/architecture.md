# Architecture
See project knowledge document 01-architecture.md for full details.

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
