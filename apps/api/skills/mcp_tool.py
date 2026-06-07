"""skills/mcp_tool — Proxy tool that wraps a remote MCP server tool as a BaseTool.

Each instance represents one tool discovered from an external MCP server.
The proxy forwards execute() calls to the remote server via the MCP client
manager, mapping results into the standard ToolResult envelope.

Security posture: RiskLevel.HIGH and approval_required=True by default,
matching the fetch_url precedent for network/external-facing tools.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from apps.api.models.run import ErrorKind, RiskLevel, ToolResult
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)

# Default permissive schema when the server provides none.
_DEFAULT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
}


class McpProxyTool(BaseTool):
    """Wraps a single remote MCP tool as a native BaseTool.

    Args:
        namespaced_name: Full tool name (mcp__{server}__{tool}).
        description: The remote tool's description.
        input_schema: The remote tool's advertised JSON schema.
        manager: The McpClientManager instance for making calls.
        risk_level: Risk classification (default HIGH).
        approval_required: Whether user approval is needed (default True).
    """

    def __init__(
        self,
        namespaced_name: str,
        description: str,
        input_schema: dict[str, Any],
        *,
        manager: Any,  # McpClientManager — Any to avoid circular import
        server_name: str,
        risk_level: RiskLevel = RiskLevel.HIGH,
        approval_required: bool = True,
    ) -> None:
        self._namespaced_name = namespaced_name
        self._description = description
        self._input_schema = input_schema or _DEFAULT_INPUT_SCHEMA
        self._manager = manager
        self._server_name = server_name
        self._risk_level = risk_level
        self._approval_required = approval_required

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name=self._namespaced_name,
            description=f"[MCP: {self._server_name}] {self._description}",
            risk_level=self._risk_level,
            approval_required=self._approval_required,
            input_schema=self._input_schema,
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        """Call the remote MCP tool and map the result to a ToolResult."""
        started = self._now()
        try:
            result = await self._manager.call_tool(self._namespaced_name, args)

            # Extract content from the MCP CallToolResult.
            # result.content is a list of content blocks (TextContent, etc.)
            # result.isError indicates whether the tool reported an error.
            content_parts: list[str] = []
            for block in (result.content or []):
                if hasattr(block, "text"):
                    content_parts.append(block.text)
                elif hasattr(block, "data"):
                    content_parts.append(f"[binary: {getattr(block, 'mimeType', 'unknown')}]")

            combined = "\n".join(content_parts)

            if result.isError:
                return self._error(
                    args, f"Remote tool error: {combined}", started,
                    error_kind=ErrorKind.PERMANENT,
                )

            # Try to parse as JSON for structured output
            output: dict[str, Any]
            try:
                parsed = json.loads(combined)
                output = {"result": parsed}
            except (json.JSONDecodeError, TypeError):
                output = {"result": combined}

            return self._success(args, output, started)

        except asyncio.TimeoutError:
            return self._error(
                args,
                f"MCP tool call timed out for {self._namespaced_name}",
                started,
                error_kind=ErrorKind.TRANSIENT,
            )
        except (ConnectionError, OSError) as exc:
            return self._error(
                args,
                f"MCP connection error: {exc}",
                started,
                error_kind=ErrorKind.TRANSIENT,
            )
        except ValueError as exc:
            return self._error(
                args,
                f"MCP tool error: {exc}",
                started,
                error_kind=ErrorKind.PERMANENT,
            )
        except Exception as exc:
            logger.error("Unexpected error calling MCP tool %s: %s",
                         self._namespaced_name, exc, exc_info=True)
            return self._error(
                args,
                f"Unexpected MCP error: {exc}",
                started,
                error_kind=ErrorKind.PERMANENT,
            )
