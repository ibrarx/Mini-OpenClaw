# API Specification
See project knowledge document 05-api-spec.md for full details.

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
