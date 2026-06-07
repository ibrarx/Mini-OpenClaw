# Architecture
See project knowledge document 01-architecture.md for full details.

## MCP Client Support

The skill registry can optionally consume tools from external MCP (Model Context Protocol) servers. When `MCP_CLIENT_ENABLED=true`:

1. **Startup** (`main.py` lifespan): `McpClientManager` connects to each configured server via stdio, SSE, or streamable-HTTP transport, performs the MCP handshake, and discovers available tools.
2. **Registration** (`registry.py`): Each discovered remote tool is wrapped in an `McpProxyTool(BaseTool)` and registered in the skill registry. Tools are namespaced as `mcp__{server}__{tool}`.
3. **Execution**: MCP proxy tools execute through the standard `BaseTool` / executor path — no changes to the orchestrator or ReAct loop.
4. **Shutdown**: All MCP client connections are torn down cleanly.

The feature is off by default and has no effect on the agent when disabled.
