"""mcp/client — Manages connections to external MCP servers.

Responsible for:
- Opening ClientSession connections over stdio/SSE/streamable-HTTP transports
- Performing the MCP initialize handshake and discovering remote tools
- Maintaining a mapping from namespaced tool names to sessions
- Routing call_tool requests to the correct session
- Graceful startup (skip failing servers) and clean shutdown
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import Tool as McpTool

logger = logging.getLogger(__name__)

# Timeout for connecting to and initializing an MCP server.
_CONNECT_TIMEOUT_S = 30.0
# Timeout for individual tool calls.
_CALL_TIMEOUT_S = 60.0

# Separator used in namespaced tool names: mcp__{server}__{tool}
NAMESPACE_SEP = "__"


@dataclass
class RemoteToolInfo:
    """Metadata about a single tool discovered from an MCP server."""
    namespaced_name: str
    server_name: str
    remote_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class _ServerConnection:
    """Internal bookkeeping for one connected MCP server."""
    name: str
    session: ClientSession
    tools: list[McpTool] = field(default_factory=list)
    # Context manager stack for cleanup (transport context managers)
    _cleanup_stack: list[Any] = field(default_factory=list)


class McpClientManager:
    """Manages the lifecycle of MCP client sessions.

    Usage::

        manager = McpClientManager(server_configs)
        await manager.connect_all()
        # ... register proxy tools, run agent ...
        await manager.aclose_all()
    """

    def __init__(self, server_configs: list[Any]) -> None:
        """
        Args:
            server_configs: List of McpServerConfig objects from Settings.
        """
        self._configs = server_configs
        self._connections: dict[str, _ServerConnection] = {}
        # namespaced_name -> (server_name, remote_tool_name)
        self._tool_map: dict[str, tuple[str, str]] = {}
        self._discovered_tools: list[RemoteToolInfo] = []

    async def connect_all(self) -> None:
        """Connect to all enabled MCP servers. Failing servers are skipped."""
        for cfg in self._configs:
            if not cfg.enabled:
                logger.info("MCP server %r is disabled — skipping", cfg.name)
                continue
            try:
                await asyncio.wait_for(
                    self._connect_one(cfg),
                    timeout=_CONNECT_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "MCP server %r timed out during connection (%.0fs) — skipping",
                    cfg.name, _CONNECT_TIMEOUT_S,
                )
            except Exception as exc:
                logger.warning(
                    "MCP server %r failed to connect: %s — skipping",
                    cfg.name, exc,
                )

    async def _connect_one(self, cfg: Any) -> None:
        """Connect to a single MCP server and discover its tools."""
        transport = cfg.transport.lower()
        conn = _ServerConnection(name=cfg.name, session=None)  # type: ignore[arg-type]

        try:
            if transport == "stdio":
                params = StdioServerParameters(
                    command=cfg.command,
                    args=cfg.args,
                )
                # stdio_client is an async context manager yielding (read, write)
                ctx = stdio_client(params, errlog=sys.stderr)
                streams = await ctx.__aenter__()
                conn._cleanup_stack.append(ctx)
                read_stream, write_stream = streams

            elif transport == "sse":
                ctx = sse_client(cfg.url, timeout=_CONNECT_TIMEOUT_S)
                streams = await ctx.__aenter__()
                conn._cleanup_stack.append(ctx)
                read_stream, write_stream = streams

            elif transport == "streamable_http":
                ctx = streamablehttp_client(cfg.url, timeout=_CONNECT_TIMEOUT_S)
                streams = await ctx.__aenter__()
                conn._cleanup_stack.append(ctx)
                read_stream, write_stream = streams[0], streams[1]

            else:
                logger.warning("MCP server %r has unsupported transport %r — skipping",
                               cfg.name, transport)
                return

            # Create and initialize the client session
            session = ClientSession(read_stream, write_stream)
            session_ctx = session.__aenter__
            await session.__aenter__()
            conn._cleanup_stack.append(session)
            conn.session = session

            # Initialize the MCP handshake
            await session.initialize()

            # Discover tools
            result = await session.list_tools()
            conn.tools = result.tools

            # Apply allowed_tools filter
            allowed = set(cfg.allowed_tools) if cfg.allowed_tools else None

            for tool in conn.tools:
                if allowed and tool.name not in allowed:
                    logger.debug("MCP server %r: tool %r not in allowed_tools — skipping",
                                 cfg.name, tool.name)
                    continue

                ns_name = f"mcp{NAMESPACE_SEP}{cfg.name}{NAMESPACE_SEP}{tool.name}"
                self._tool_map[ns_name] = (cfg.name, tool.name)

                # Extract input schema, defaulting to permissive object
                input_schema = {}
                if tool.inputSchema:
                    input_schema = (
                        tool.inputSchema
                        if isinstance(tool.inputSchema, dict)
                        else tool.inputSchema.model_dump() if hasattr(tool.inputSchema, "model_dump")
                        else {}
                    )

                self._discovered_tools.append(RemoteToolInfo(
                    namespaced_name=ns_name,
                    server_name=cfg.name,
                    remote_name=tool.name,
                    description=tool.description or f"Remote tool from {cfg.name}",
                    input_schema=input_schema,
                ))

            self._connections[cfg.name] = conn
            logger.info(
                "MCP server %r connected: %d tools discovered, %d registered after filtering",
                cfg.name,
                len(conn.tools),
                sum(1 for t in self._discovered_tools if t.server_name == cfg.name),
            )

        except Exception:
            # Clean up partially opened resources on failure
            await self._cleanup_connection(conn)
            raise

    async def call_tool(self, namespaced_name: str, arguments: dict[str, Any]) -> Any:
        """Call a remote tool by its namespaced name.

        Args:
            namespaced_name: The full namespaced name (mcp__{server}__{tool}).
            arguments: The tool arguments dict.

        Returns:
            The MCP CallToolResult.

        Raises:
            ValueError: If the tool is not found.
            TimeoutError: If the call exceeds the timeout.
            Exception: Any transport or protocol error.
        """
        if namespaced_name not in self._tool_map:
            raise ValueError(f"Unknown MCP tool: {namespaced_name!r}")

        server_name, remote_name = self._tool_map[namespaced_name]
        conn = self._connections.get(server_name)
        if conn is None or conn.session is None:
            raise ValueError(f"MCP server {server_name!r} is not connected")

        return await asyncio.wait_for(
            conn.session.call_tool(remote_name, arguments),
            timeout=_CALL_TIMEOUT_S,
        )

    @property
    def discovered_tools(self) -> list[RemoteToolInfo]:
        """All discovered (and filtered) remote tools across all servers."""
        return list(self._discovered_tools)

    @property
    def connected_server_count(self) -> int:
        return len(self._connections)

    async def aclose_all(self) -> None:
        """Shut down all MCP server connections."""
        for name, conn in list(self._connections.items()):
            try:
                await self._cleanup_connection(conn)
            except Exception as exc:
                logger.warning("Error closing MCP server %r: %s", name, exc)
        self._connections.clear()
        self._tool_map.clear()
        self._discovered_tools.clear()
        logger.info("All MCP client connections closed")

    async def _cleanup_connection(self, conn: _ServerConnection) -> None:
        """Tear down a single server connection's resources in reverse order."""
        for ctx in reversed(conn._cleanup_stack):
            try:
                await ctx.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("Cleanup error for %r: %s", conn.name, exc)
        conn._cleanup_stack.clear()
