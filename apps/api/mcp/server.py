"""mcp/server — Expose Mini-OpenClaw tools to external MCP clients.

Builds an MCP Server that translates registered tool manifests into MCP tool
definitions and routes incoming call_tool requests through the same
policy-checked, audit-logged executor path used by the internal agent.

Safety model:
- Default exposed set = read-only safe tools only (list_files, read_file,
  search_in_files, search_memory).
- Approval-gated tools are refused with an MCP error unless the operator
  explicitly opts in via MCP_SERVER_EXPOSED_TOOLS + MCP_SERVER_REQUIRE_APPROVAL=false.
- All calls pass through PolicyEngine and Executor (path sandbox, command
  allowlist, read-only mount enforcement all apply).
- Every invocation produces an audit record consistent with internal executions.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, TYPE_CHECKING

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool as McpToolDef

if TYPE_CHECKING:
    from apps.api.core.orchestrator import Orchestrator
    from apps.api.skills.registry import SkillRegistry
    from apps.api.config import Settings

logger = logging.getLogger(__name__)

# Tools that are safe and non-mutating — the default exposed set when the
# operator does not specify an explicit allowlist.
_SAFE_DEFAULT_TOOLS: frozenset[str] = frozenset({
    "list_files",
    "read_file",
    "search_in_files",
    "search_memory",
})

# Tools that must never be exposed over MCP regardless of allowlist — they
# spawn internal runs or background work with no sane remote semantics.
_NEVER_EXPOSE: frozenset[str] = frozenset({
    "delegate_task",
    "schedule_task",
})

# Timeout for a single MCP tool call (seconds).
_CALL_TIMEOUT_S = 60.0


class McpServerBridge:
    """Bridges the MCP protocol to Mini-OpenClaw's tool execution pipeline.

    Created at startup and wired into the FastAPI lifespan.  Provides:
    - ``mcp_server`` — the ``mcp.server.Server`` instance with handlers
    - ``sse_transport`` — the ``SseServerTransport`` for mounting on FastAPI
    - ``exposed_tool_names`` — the computed set of tools actually exposed
    """

    def __init__(
        self,
        settings: Settings,
        registry: SkillRegistry,
        orchestrator: Orchestrator,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._orchestrator = orchestrator
        self._exposed: set[str] = set()

        # Compute exposed tool set
        self._compute_exposed_tools()

        # Build MCP server
        self._server = Server("mini-openclaw")

        # Build SSE transport — endpoint is the POST path for client messages
        mcp_path = settings.mcp_server_path.rstrip("/")
        self._sse_transport = SseServerTransport(f"{mcp_path}/messages/")

        # Register MCP handlers
        self._register_handlers()

    # ── public ───────────────────────────────────────────────

    @property
    def mcp_server(self) -> Server:
        return self._server

    @property
    def sse_transport(self) -> SseServerTransport:
        return self._sse_transport

    @property
    def exposed_tool_names(self) -> frozenset[str]:
        return frozenset(self._exposed)

    # ── private ──────────────────────────────────────────────

    def _compute_exposed_tools(self) -> None:
        """Determine which tools to expose, validating against the registry."""
        all_tool_names = {t.manifest().name for t in self._registry.list_tools()}
        explicit_list = self._settings.mcp_server_exposed_tools
        require_approval = self._settings.mcp_server_require_approval

        if explicit_list:
            # Operator provided an explicit allowlist
            for name in explicit_list:
                if name in _NEVER_EXPOSE:
                    logger.warning(
                        "MCP server: tool %r is in the never-expose list and will be skipped",
                        name,
                    )
                    continue
                if name not in all_tool_names:
                    logger.warning(
                        "MCP server: tool %r in MCP_SERVER_EXPOSED_TOOLS not found in registry — skipping",
                        name,
                    )
                    continue

                tool = self._registry.get(name)
                if tool is None:
                    continue
                manifest = tool.manifest()

                if manifest.approval_required and require_approval:
                    logger.warning(
                        "MCP server: tool %r is approval-gated and MCP_SERVER_REQUIRE_APPROVAL=true "
                        "— it will be listed but calls will be refused. Set "
                        "MCP_SERVER_REQUIRE_APPROVAL=false to allow remote execution.",
                        name,
                    )

                self._exposed.add(name)
        else:
            # No explicit list → safe defaults only
            for name in _SAFE_DEFAULT_TOOLS:
                if name in all_tool_names:
                    self._exposed.add(name)
                else:
                    logger.debug("MCP server: safe-default tool %r not in registry", name)

        if not require_approval and explicit_list:
            approval_tools = []
            for name in self._exposed:
                tool = self._registry.get(name)
                if tool and tool.manifest().approval_required:
                    approval_tools.append(name)
            if approval_tools:
                logger.warning(
                    "MCP server: approval gating DISABLED for MCP callers. "
                    "The following mutating tools are executable by remote clients: %s",
                    ", ".join(sorted(approval_tools)),
                )

        logger.info(
            "MCP server: exposing %d tool(s): %s",
            len(self._exposed),
            ", ".join(sorted(self._exposed)) or "(none)",
        )

    def _register_handlers(self) -> None:
        """Register list_tools and call_tool on the MCP Server."""

        @self._server.list_tools()
        async def handle_list_tools() -> list[McpToolDef]:
            tools: list[McpToolDef] = []
            for name in sorted(self._exposed):
                tool = self._registry.get(name)
                if tool is None:
                    continue
                manifest = tool.manifest()
                tools.append(McpToolDef(
                    name=manifest.name,
                    description=manifest.description,
                    inputSchema=manifest.input_schema,
                ))
            return tools

        @self._server.call_tool()
        async def handle_call_tool(
            name: str,
            arguments: dict[str, Any] | None = None,
        ) -> list[TextContent]:
            return await self._execute_tool(name, arguments or {})

    async def _execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> list[TextContent]:
        """Execute a tool through the full policy/executor pipeline.

        Returns MCP-compatible content (TextContent list). Never raises — all
        errors are mapped to MCP error content.
        """
        # 1. Check tool is in exposed set
        if name not in self._exposed:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Tool {name!r} is not available over MCP.",
                    "code": "TOOL_NOT_EXPOSED",
                }),
            )]

        # 2. Check tool exists in registry
        tool = self._registry.get(name)
        if tool is None:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Tool {name!r} not found in registry.",
                    "code": "TOOL_NOT_FOUND",
                }),
            )]

        # 3. Check approval policy
        manifest = tool.manifest()
        if manifest.approval_required and self._settings.mcp_server_require_approval:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": (
                        f"Tool {name!r} requires human approval which is not available "
                        f"over MCP. Set MCP_SERVER_REQUIRE_APPROVAL=false and add the "
                        f"tool to MCP_SERVER_EXPOSED_TOOLS to enable remote execution."
                    ),
                    "code": "APPROVAL_REQUIRED",
                }),
            )]

        # 4. Build ToolContext (reuse orchestrator's context construction)
        run_id = f"mcp-{uuid.uuid4().hex[:12]}"
        step_id = f"mcp-step-{uuid.uuid4().hex[:8]}"
        context = self._orchestrator.build_tool_context(
            run_id=run_id,
            step_id=step_id,
        )

        # 5. Audit: log the MCP tool invocation
        try:
            await self._orchestrator.audit.log(
                "mcp_tool_called",
                run_id=run_id,
                step_id=step_id,
                data={"tool": name, "args": arguments, "source": "mcp_server"},
            )
        except Exception as exc:
            logger.warning("Failed to log MCP audit event: %s", exc)

        # 6. Execute through the executor (includes policy validation, retries)
        try:
            result = await asyncio.wait_for(
                self._orchestrator.executor.execute_tool(name, arguments, context),
                timeout=_CALL_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.error("MCP tool call %r timed out after %.0fs", name, _CALL_TIMEOUT_S)
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Tool {name!r} execution timed out.",
                    "code": "TIMEOUT",
                }),
            )]
        except Exception as exc:
            logger.error("MCP tool call %r failed: %s", name, exc, exc_info=True)
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Internal error executing tool {name!r}: {exc}",
                    "code": "INTERNAL_ERROR",
                }),
            )]

        # 7. Audit: log the result
        try:
            event_type = "mcp_tool_completed" if result.status == "success" else "mcp_tool_failed"
            await self._orchestrator.audit.log(
                event_type,
                run_id=run_id,
                step_id=step_id,
                data={
                    "tool": name,
                    "status": result.status,
                    "error": result.error,
                },
            )
        except Exception as exc:
            logger.warning("Failed to log MCP audit result: %s", exc)

        # 8. Translate ToolResult → MCP content
        if result.status == "success":
            payload = result.output if result.output is not None else {}
            return [TextContent(
                type="text",
                text=json.dumps(payload, default=str),
            )]
        else:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": result.error or "Unknown error",
                    "code": "TOOL_ERROR",
                }),
            )]
