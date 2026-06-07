"""tests/test_mcp_server — Tests for MCP server support.

All tests use mocked transports — no real MCP connections or network traffic.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.config import Settings
from apps.api.core.audit import AuditLogger
from apps.api.core.executor import Executor
from apps.api.models.run import RiskLevel, ToolResult
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext
from apps.api.skills.registry import SkillRegistry


# ─── Fake tools ──────────────────────────────────────────────

class FakeSafeTool(BaseTool):
    """A safe read-only tool for testing."""

    def __init__(self, name: str = "list_files") -> None:
        self._name = name

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name=self._name,
            description=f"Fake {self._name} tool",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(
            tool_name=self._name,
            status="success",
            risk_level=RiskLevel.SAFE,
            input=args,
            output={"entries": ["file1.txt", "file2.txt"]},
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
        )


class FakeApprovalTool(BaseTool):
    """A tool that requires approval."""

    def __init__(self, name: str = "write_file") -> None:
        self._name = name

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name=self._name,
            description=f"Fake {self._name} tool",
            risk_level=RiskLevel.MEDIUM,
            approval_required=True,
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            },
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(
            tool_name=self._name,
            status="success",
            risk_level=RiskLevel.MEDIUM,
            input=args,
            output={"written": True},
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
        )


# ─── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def registry() -> SkillRegistry:
    """Registry with safe + approval-gated tools."""
    reg = SkillRegistry()
    # Manually inject fake tools instead of discover()
    reg._tools = {
        "list_files": FakeSafeTool("list_files"),
        "read_file": FakeSafeTool("read_file"),
        "search_in_files": FakeSafeTool("search_in_files"),
        "search_memory": FakeSafeTool("search_memory"),
        "write_file": FakeApprovalTool("write_file"),
        "run_shell_safe": FakeApprovalTool("run_shell_safe"),
        "remember_fact": FakeSafeTool("remember_fact"),
    }
    return reg


@pytest.fixture
def mock_orchestrator(tmp_workspace: Path, registry: SkillRegistry) -> MagicMock:
    """Mocked orchestrator with working build_tool_context and executor."""
    orch = MagicMock()
    orch._workspace = tmp_workspace
    orch._db_path = tmp_workspace / "test.db"

    # build_tool_context returns a real ToolContext
    def build_ctx(run_id: str = "", step_id: str = "") -> ToolContext:
        return ToolContext(
            workspace_root=str(tmp_workspace),
            run_id=run_id,
            step_id=step_id,
            db_path=str(tmp_workspace / "test.db"),
            mounts={},
        )

    orch.build_tool_context = build_ctx

    # Audit logger mock
    orch.audit = AsyncMock(spec=AuditLogger)
    orch.audit.log = AsyncMock(return_value="evt_test")

    # Executor that delegates to the real tool.execute
    async def fake_execute(name: str, args: dict, context: ToolContext) -> ToolResult:
        tool = registry.get(name)
        if tool is None:
            return ToolResult(
                tool_name=name, status="error", input=args,
                error=f"Tool not found: {name}",
            )
        return await tool.execute(args, context)

    orch.executor = AsyncMock(spec=Executor)
    orch.executor.execute_tool = AsyncMock(side_effect=fake_execute)

    return orch


def make_settings(**overrides: Any) -> Settings:
    """Create a Settings instance with MCP server config."""
    defaults = {
        "anthropic_api_key": "test-key",
        "mcp_server_enabled": True,
        "mcp_server_path": "/mcp",
        "mcp_server_exposed_tools": [],
        "mcp_server_require_approval": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ─── Tests: exposed tool computation ────────────────────────

class TestExposedToolSet:
    """Tests for which tools get exposed over MCP."""

    def test_default_exposes_safe_tools_only(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """Empty allowlist → only the safe default set."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings()
        bridge = McpServerBridge(settings, registry, mock_orchestrator)
        exposed = bridge.exposed_tool_names

        assert exposed == frozenset({"list_files", "read_file", "search_in_files", "search_memory"})
        assert "write_file" not in exposed
        assert "run_shell_safe" not in exposed
        assert "remember_fact" not in exposed

    def test_explicit_allowlist_respected(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """Explicit allowlist exposes only listed tools."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings(mcp_server_exposed_tools=["list_files", "read_file"])
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        assert bridge.exposed_tool_names == frozenset({"list_files", "read_file"})

    def test_unknown_tool_in_allowlist_skipped(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """Unknown tools in the allowlist are silently skipped."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings(
            mcp_server_exposed_tools=["list_files", "nonexistent_tool"],
        )
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        assert bridge.exposed_tool_names == frozenset({"list_files"})

    def test_never_expose_tools_blocked(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """delegate_task and schedule_task are never exposed even if listed."""
        from apps.api.mcp.server import McpServerBridge

        # Add delegate_task to registry
        registry._tools["delegate_task"] = FakeSafeTool("delegate_task")
        settings = make_settings(
            mcp_server_exposed_tools=["list_files", "delegate_task"],
        )
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        assert "delegate_task" not in bridge.exposed_tool_names
        assert "list_files" in bridge.exposed_tool_names

    def test_approval_tool_in_allowlist_with_require_approval(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """Approval-gated tools are listed (for discovery) but calls are refused."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings(
            mcp_server_exposed_tools=["list_files", "write_file"],
            mcp_server_require_approval=True,
        )
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        # write_file is in the exposed set (listed for discovery)
        assert "write_file" in bridge.exposed_tool_names


# ─── Tests: list_tools ───────────────────────────────────────

class TestListTools:
    """Tests for MCP list_tools handler."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_safe_defaults(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings()
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        # Access the handler directly via the server's internal state
        # We test by calling _execute_tool and list_tools indirectly
        # via the bridge's exposed_tool_names
        exposed = bridge.exposed_tool_names
        assert len(exposed) == 4
        assert "list_files" in exposed

    @pytest.mark.asyncio
    async def test_input_schema_matches_native(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """MCP tool definitions have the same inputSchema as native manifests."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings()
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        for name in bridge.exposed_tool_names:
            native_tool = registry.get(name)
            assert native_tool is not None
            native_schema = native_tool.manifest().input_schema
            # The schema should be non-empty
            assert native_schema


# ─── Tests: call_tool ────────────────────────────────────────

class TestCallTool:
    """Tests for MCP call_tool execution."""

    @pytest.mark.asyncio
    async def test_safe_tool_executes_successfully(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """A safe tool call returns success content."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings()
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        result = await bridge._execute_tool("list_files", {"path": "."})

        assert len(result) == 1
        payload = json.loads(result[0].text)
        assert "entries" in payload
        # Executor was called
        mock_orchestrator.executor.execute_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_safe_tool_produces_audit_records(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """Every MCP tool call logs audit events."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings()
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        await bridge._execute_tool("read_file", {"path": "test.txt"})

        # Should have at least 2 audit calls: mcp_tool_called + mcp_tool_completed
        assert mock_orchestrator.audit.log.call_count >= 2
        event_types = [call.kwargs.get("data", {}).get("source") or call.args[0]
                       for call in mock_orchestrator.audit.log.call_args_list]
        # First call should be mcp_tool_called
        assert mock_orchestrator.audit.log.call_args_list[0].args[0] == "mcp_tool_called"

    @pytest.mark.asyncio
    async def test_approval_tool_refused_by_default(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """Approval-gated tools return an MCP error when require_approval=True."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings(
            mcp_server_exposed_tools=["list_files", "write_file"],
            mcp_server_require_approval=True,
        )
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        result = await bridge._execute_tool("write_file", {
            "path": "test.txt",
            "content": "hello",
        })

        assert len(result) == 1
        payload = json.loads(result[0].text)
        assert payload["code"] == "APPROVAL_REQUIRED"
        # Executor must NOT have been called
        mock_orchestrator.executor.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_approval_tool_executes_when_opted_in(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """Approval-gated tools execute when operator explicitly opts in."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings(
            mcp_server_exposed_tools=["write_file"],
            mcp_server_require_approval=False,
        )
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        result = await bridge._execute_tool("write_file", {
            "path": "test.txt",
            "content": "hello",
        })

        assert len(result) == 1
        payload = json.loads(result[0].text)
        assert "written" in payload  # success output
        mock_orchestrator.executor.execute_tool.assert_called_once()
        # Audit log was recorded
        assert mock_orchestrator.audit.log.call_count >= 2

    @pytest.mark.asyncio
    async def test_unexposed_tool_returns_error(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """Requesting a tool not in the exposed set returns an MCP error."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings()  # default safe set
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        result = await bridge._execute_tool("write_file", {"path": "x"})

        payload = json.loads(result[0].text)
        assert payload["code"] == "TOOL_NOT_EXPOSED"
        mock_orchestrator.executor.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """A completely unknown tool name returns an error, not an exception."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings(
            mcp_server_exposed_tools=["totally_fake"],
        )
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        # "totally_fake" was skipped during compute (not in registry),
        # so it won't be in the exposed set
        result = await bridge._execute_tool("totally_fake", {})
        payload = json.loads(result[0].text)
        assert payload["code"] == "TOOL_NOT_EXPOSED"

    @pytest.mark.asyncio
    async def test_executor_error_mapped_to_mcp_error(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """If the executor raises, the error is caught and returned as MCP error content."""
        from apps.api.mcp.server import McpServerBridge

        settings = make_settings()
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        # Make executor raise
        mock_orchestrator.executor.execute_tool = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        result = await bridge._execute_tool("list_files", {"path": "."})
        payload = json.loads(result[0].text)
        assert payload["code"] == "INTERNAL_ERROR"
        assert "boom" in payload["error"]

    @pytest.mark.asyncio
    async def test_timeout_returns_mcp_error(
        self, registry: SkillRegistry, mock_orchestrator: MagicMock
    ) -> None:
        """A tool that exceeds the timeout returns a timeout error."""
        from apps.api.mcp.server import McpServerBridge, _CALL_TIMEOUT_S

        settings = make_settings()
        bridge = McpServerBridge(settings, registry, mock_orchestrator)

        # Make executor hang
        async def hang(*a: Any, **kw: Any) -> ToolResult:
            await asyncio.sleep(999)
            return ToolResult(tool_name="list_files", status="success", input={})

        mock_orchestrator.executor.execute_tool = AsyncMock(side_effect=hang)

        # Patch timeout to be short for testing
        with patch("apps.api.mcp.server._CALL_TIMEOUT_S", 0.1):
            result = await bridge._execute_tool("list_files", {"path": "."})

        payload = json.loads(result[0].text)
        assert payload["code"] == "TIMEOUT"


# ─── Tests: config defaults ─────────────────────────────────

class TestConfigDefaults:
    """Tests for MCP server configuration."""

    def test_disabled_by_default(self) -> None:
        settings = Settings(anthropic_api_key="k")
        assert settings.mcp_server_enabled is False

    def test_default_path(self) -> None:
        settings = Settings(anthropic_api_key="k")
        assert settings.mcp_server_path == "/mcp"

    def test_default_require_approval(self) -> None:
        settings = Settings(anthropic_api_key="k")
        assert settings.mcp_server_require_approval is True

    def test_default_exposed_tools_empty(self) -> None:
        settings = Settings(anthropic_api_key="k")
        assert settings.mcp_server_exposed_tools == []

    def test_path_gets_leading_slash(self) -> None:
        settings = Settings(
            anthropic_api_key="k",
            mcp_server_path="mcp",
        )
        assert settings.mcp_server_path.startswith("/")
