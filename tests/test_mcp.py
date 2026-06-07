"""tests/test_mcp — Tests for MCP client support.

All tests use mocked MCP sessions — no real servers or network traffic.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.models.run import ErrorKind, RiskLevel
from apps.api.skills.base import ToolContext
from apps.api.skills.mcp_tool import McpProxyTool


# ─── Fake MCP types ──────────────────────────────────────────

@dataclass
class FakeMcpTool:
    """Mimics mcp.types.Tool for testing."""
    name: str
    description: str
    inputSchema: dict[str, Any] | None = None


@dataclass
class FakeTextContent:
    type: str = "text"
    text: str = ""


@dataclass
class FakeCallToolResult:
    content: list[Any] = None
    isError: bool = False

    def __post_init__(self):
        if self.content is None:
            self.content = []


@dataclass
class FakeListToolsResult:
    tools: list[FakeMcpTool]


class FakeMcpClientManager:
    """Minimal mock of McpClientManager for proxy tool tests."""

    def __init__(self, tools: list[tuple[str, str, str, dict]], *, fail_tools: set[str] | None = None):
        """
        Args:
            tools: List of (namespaced_name, server_name, remote_name, input_schema) tuples.
            fail_tools: Set of namespaced names that should raise on call.
        """
        from apps.api.mcp.client import RemoteToolInfo
        self._tools = {t[0]: t for t in tools}
        self._fail_tools = fail_tools or set()
        self._discovered = [
            RemoteToolInfo(
                namespaced_name=t[0],
                server_name=t[1],
                remote_name=t[2],
                description=f"Test tool {t[2]}",
                input_schema=t[3],
            )
            for t in tools
        ]

    @property
    def discovered_tools(self):
        return self._discovered

    @property
    def connected_server_count(self) -> int:
        servers = set(t[1] for t in self._tools.values())
        return len(servers)

    async def call_tool(self, namespaced_name: str, arguments: dict) -> FakeCallToolResult:
        if namespaced_name in self._fail_tools:
            raise ConnectionError("Simulated connection failure")
        if namespaced_name not in self._tools:
            raise ValueError(f"Unknown tool: {namespaced_name}")
        return FakeCallToolResult(
            content=[FakeTextContent(text='{"status": "ok"}')],
            isError=False,
        )

    async def connect_all(self) -> None:
        pass

    async def aclose_all(self) -> None:
        pass


# ─── Fixtures ─────────────────────────────────────────────────

WORKSPACE = "/tmp/test-mcp-workspace"


@pytest.fixture
def ctx() -> ToolContext:
    return ToolContext(workspace_root=WORKSPACE, run_id="test-run", step_id="step-1")


@pytest.fixture
def mock_manager() -> FakeMcpClientManager:
    return FakeMcpClientManager([
        ("mcp__testsvr__greet", "testsvr", "greet", {"type": "object", "properties": {"name": {"type": "string"}}}),
        ("mcp__testsvr__calc", "testsvr", "calc", {"type": "object", "properties": {"expr": {"type": "string"}}}),
    ])


@pytest.fixture
def proxy_tool(mock_manager: FakeMcpClientManager) -> McpProxyTool:
    return McpProxyTool(
        namespaced_name="mcp__testsvr__greet",
        description="Say hello",
        input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
        manager=mock_manager,
        server_name="testsvr",
    )


# ─── Config validation tests ─────────────────────────────────

class TestMcpServerConfig:

    def test_valid_stdio_config(self) -> None:
        from apps.api.config import McpServerConfig
        cfg = McpServerConfig(
            name="fs", transport="stdio", command="npx",
            args=["-y", "@anthropic/mcp-filesystem"],
        )
        assert cfg.name == "fs"
        assert cfg.enabled is True
        assert cfg.approval_required is True

    def test_valid_sse_config(self) -> None:
        from apps.api.config import McpServerConfig
        cfg = McpServerConfig(
            name="weather", transport="sse",
            url="http://localhost:3001/sse",
        )
        assert cfg.transport == "sse"
        assert cfg.url == "http://localhost:3001/sse"

    def test_valid_streamable_http_config(self) -> None:
        from apps.api.config import McpServerConfig
        cfg = McpServerConfig(
            name="api", transport="streamable_http",
            url="http://localhost:3002/mcp",
        )
        assert cfg.transport == "streamable_http"

    def test_settings_validation_rejects_invalid_transport(self) -> None:
        from apps.api.config import Settings
        with pytest.raises(ValueError, match="transport must be one of"):
            Settings(
                mcp_client_enabled=True,
                mcp_servers=[{"name": "bad", "transport": "websocket"}],
            )

    def test_settings_validation_rejects_duplicate_names(self) -> None:
        from apps.api.config import Settings
        with pytest.raises(ValueError, match="Duplicate MCP server name"):
            Settings(
                mcp_client_enabled=True,
                mcp_servers=[
                    {"name": "fs", "transport": "stdio", "command": "cmd1"},
                    {"name": "fs", "transport": "stdio", "command": "cmd2"},
                ],
            )

    def test_settings_validation_rejects_reserved_names(self) -> None:
        from apps.api.config import Settings
        with pytest.raises(ValueError, match="reserved"):
            Settings(
                mcp_client_enabled=True,
                mcp_servers=[{"name": "system", "transport": "stdio", "command": "cmd"}],
            )

    def test_settings_validation_requires_command_for_stdio(self) -> None:
        from apps.api.config import Settings
        with pytest.raises(ValueError, match="command.*required"):
            Settings(
                mcp_client_enabled=True,
                mcp_servers=[{"name": "fs", "transport": "stdio"}],
            )

    def test_settings_validation_requires_url_for_sse(self) -> None:
        from apps.api.config import Settings
        with pytest.raises(ValueError, match="url.*required"):
            Settings(
                mcp_client_enabled=True,
                mcp_servers=[{"name": "web", "transport": "sse"}],
            )

    def test_settings_disabled_by_default(self) -> None:
        from apps.api.config import Settings
        s = Settings()
        assert s.mcp_client_enabled is False
        assert s.mcp_servers == []


# ─── Registry integration tests ──────────────────────────────

class TestRegistryMcpIntegration:

    def test_no_mcp_tools_when_disabled(self) -> None:
        """With mcp_client_enabled=False, tool count matches pre-change baseline."""
        from apps.api.skills.registry import SkillRegistry
        from apps.api.config import Settings

        reg = SkillRegistry()
        settings = Settings(mcp_client_enabled=False)
        reg.discover(settings=settings)
        baseline_count = reg.tool_count

        # Same count even when passing a manager (should be ignored since disabled)
        reg2 = SkillRegistry()
        reg2.discover(settings=settings, mcp_manager=None)
        assert reg2.tool_count == baseline_count

    def test_mcp_proxy_tools_registered(self, mock_manager: FakeMcpClientManager) -> None:
        """With MCP enabled, proxy tools are registered with correct names."""
        from apps.api.skills.registry import SkillRegistry
        from apps.api.config import Settings

        settings = Settings(
            mcp_client_enabled=True,
            mcp_servers=[{"name": "testsvr", "transport": "stdio", "command": "test"}],
        )

        reg_without = SkillRegistry()
        reg_without.discover(settings=settings)
        baseline = reg_without.tool_count

        reg_with = SkillRegistry()
        reg_with.discover(settings=settings, mcp_manager=mock_manager)
        assert reg_with.tool_count == baseline + 2

        # Check namespaced names
        assert reg_with.get("mcp__testsvr__greet") is not None
        assert reg_with.get("mcp__testsvr__calc") is not None

    def test_mcp_tools_not_in_child_runs(self, mock_manager: FakeMcpClientManager) -> None:
        """MCP tools are excluded from child/delegated runs."""
        from apps.api.skills.registry import SkillRegistry
        from apps.api.config import Settings

        settings = Settings(
            mcp_client_enabled=True,
            mcp_servers=[{"name": "testsvr", "transport": "stdio", "command": "test"}],
        )
        reg = SkillRegistry()
        reg.discover(settings=settings, mcp_manager=mock_manager, is_child_run=True)
        assert reg.get("mcp__testsvr__greet") is None
        assert reg.get("mcp__testsvr__calc") is None

    def test_allowed_tools_filter(self) -> None:
        """Per-server allowed_tools restricts which proxies appear."""
        from apps.api.skills.registry import SkillRegistry
        from apps.api.config import Settings

        # Manager with 2 tools but allowed_tools filters to 1
        manager = FakeMcpClientManager([
            ("mcp__testsvr__greet", "testsvr", "greet", {}),
        ])

        settings = Settings(
            mcp_client_enabled=True,
            mcp_servers=[{
                "name": "testsvr", "transport": "stdio", "command": "test",
                "allowed_tools": ["greet"],
            }],
        )

        reg = SkillRegistry()
        reg.discover(settings=settings, mcp_manager=manager)
        assert reg.get("mcp__testsvr__greet") is not None

    def test_planner_descriptions_include_mcp(self, mock_manager: FakeMcpClientManager) -> None:
        """MCP proxy tools flow into get_planner_descriptions()."""
        from apps.api.skills.registry import SkillRegistry
        from apps.api.config import Settings

        settings = Settings(
            mcp_client_enabled=True,
            mcp_servers=[{"name": "testsvr", "transport": "stdio", "command": "test"}],
        )
        reg = SkillRegistry()
        reg.discover(settings=settings, mcp_manager=mock_manager)

        descs = reg.get_planner_descriptions()
        names = [d["name"] for d in descs]
        assert "mcp__testsvr__greet" in names
        assert "mcp__testsvr__calc" in names


# ─── McpProxyTool tests ──────────────────────────────────────

class TestMcpProxyTool:

    def test_manifest_defaults(self, proxy_tool: McpProxyTool) -> None:
        m = proxy_tool.manifest()
        assert m.name == "mcp__testsvr__greet"
        assert m.risk_level == RiskLevel.HIGH
        assert m.approval_required is True
        assert "[MCP: testsvr]" in m.description

    def test_manifest_custom_approval(self, mock_manager: FakeMcpClientManager) -> None:
        tool = McpProxyTool(
            namespaced_name="mcp__testsvr__greet",
            description="Say hello",
            input_schema={},
            manager=mock_manager,
            server_name="testsvr",
            approval_required=False,
        )
        assert tool.manifest().approval_required is False

    @pytest.mark.asyncio
    async def test_execute_success(self, proxy_tool: McpProxyTool, ctx: ToolContext) -> None:
        result = await proxy_tool.execute({"name": "world"}, ctx)
        assert result.status == "success"
        assert result.output is not None
        # The fake manager returns JSON, so it should be parsed
        assert result.output["result"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_execute_remote_error(self, ctx: ToolContext) -> None:
        """When the remote tool reports isError=True, we get a ToolResult error."""
        manager = MagicMock()
        manager.call_tool = AsyncMock(return_value=FakeCallToolResult(
            content=[FakeTextContent(text="Something went wrong")],
            isError=True,
        ))

        tool = McpProxyTool(
            namespaced_name="mcp__srv__fail",
            description="Failing tool",
            input_schema={},
            manager=manager,
            server_name="srv",
        )
        result = await tool.execute({}, ctx)
        assert result.status == "error"
        assert result.error_kind == ErrorKind.PERMANENT
        assert "Remote tool error" in result.error

    @pytest.mark.asyncio
    async def test_execute_timeout(self, ctx: ToolContext) -> None:
        """Timeout during call_tool produces a TRANSIENT error."""
        manager = MagicMock()
        manager.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())

        tool = McpProxyTool(
            namespaced_name="mcp__srv__slow",
            description="Slow tool",
            input_schema={},
            manager=manager,
            server_name="srv",
        )
        result = await tool.execute({}, ctx)
        assert result.status == "error"
        assert result.error_kind == ErrorKind.TRANSIENT
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_connection_error(self, ctx: ToolContext) -> None:
        """Connection errors produce a TRANSIENT error."""
        manager = FakeMcpClientManager(
            [("mcp__srv__net", "srv", "net", {})],
            fail_tools={"mcp__srv__net"},
        )
        tool = McpProxyTool(
            namespaced_name="mcp__srv__net",
            description="Net tool",
            input_schema={},
            manager=manager,
            server_name="srv",
        )
        result = await tool.execute({}, ctx)
        assert result.status == "error"
        assert result.error_kind == ErrorKind.TRANSIENT

    @pytest.mark.asyncio
    async def test_execute_value_error(self, ctx: ToolContext) -> None:
        """ValueError (e.g. unknown tool) produces a PERMANENT error."""
        manager = MagicMock()
        manager.call_tool = AsyncMock(side_effect=ValueError("Unknown tool"))

        tool = McpProxyTool(
            namespaced_name="mcp__srv__unknown",
            description="Unknown tool",
            input_schema={},
            manager=manager,
            server_name="srv",
        )
        result = await tool.execute({}, ctx)
        assert result.status == "error"
        assert result.error_kind == ErrorKind.PERMANENT

    @pytest.mark.asyncio
    async def test_execute_never_raises(self, ctx: ToolContext) -> None:
        """Unexpected exceptions are caught and returned as errors, never raised."""
        manager = MagicMock()
        manager.call_tool = AsyncMock(side_effect=RuntimeError("Unexpected"))

        tool = McpProxyTool(
            namespaced_name="mcp__srv__boom",
            description="Boom",
            input_schema={},
            manager=manager,
            server_name="srv",
        )
        # Should not raise
        result = await tool.execute({}, ctx)
        assert result.status == "error"
        assert "Unexpected" in result.error

    @pytest.mark.asyncio
    async def test_execute_plain_text_result(self, ctx: ToolContext) -> None:
        """Non-JSON text result is returned as a string."""
        manager = MagicMock()
        manager.call_tool = AsyncMock(return_value=FakeCallToolResult(
            content=[FakeTextContent(text="Hello, world!")],
            isError=False,
        ))

        tool = McpProxyTool(
            namespaced_name="mcp__srv__txt",
            description="Text tool",
            input_schema={},
            manager=manager,
            server_name="srv",
        )
        result = await tool.execute({}, ctx)
        assert result.status == "success"
        assert result.output["result"] == "Hello, world!"


# ─── McpClientManager unit tests ─────────────────────────────

class TestMcpClientManager:

    def test_discovered_tools_empty_by_default(self) -> None:
        from apps.api.mcp.client import McpClientManager
        mgr = McpClientManager([])
        assert mgr.discovered_tools == []
        assert mgr.connected_server_count == 0

    @pytest.mark.asyncio
    async def test_connect_all_skips_disabled(self) -> None:
        from apps.api.config import McpServerConfig
        from apps.api.mcp.client import McpClientManager

        cfg = McpServerConfig(
            name="disabled_srv", transport="stdio", command="echo",
            enabled=False,
        )
        mgr = McpClientManager([cfg])
        await mgr.connect_all()
        assert mgr.connected_server_count == 0

    @pytest.mark.asyncio
    async def test_connect_all_survives_failure(self) -> None:
        """A failing server is skipped — does not crash connect_all."""
        from apps.api.config import McpServerConfig
        from apps.api.mcp.client import McpClientManager

        cfg = McpServerConfig(
            name="broken", transport="stdio", command="/nonexistent/binary",
        )
        mgr = McpClientManager([cfg])
        # Should not raise
        await mgr.connect_all()
        assert mgr.connected_server_count == 0
        assert mgr.discovered_tools == []

    @pytest.mark.asyncio
    async def test_call_tool_unknown_raises(self) -> None:
        from apps.api.mcp.client import McpClientManager
        mgr = McpClientManager([])
        with pytest.raises(ValueError, match="Unknown MCP tool"):
            await mgr.call_tool("mcp__nonexistent__tool", {})

    @pytest.mark.asyncio
    async def test_aclose_all_idempotent(self) -> None:
        from apps.api.mcp.client import McpClientManager
        mgr = McpClientManager([])
        await mgr.aclose_all()
        await mgr.aclose_all()  # second call should be safe
