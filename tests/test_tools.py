"""
Tests for the V1 tool implementations.

Each tool is tested in isolation with a temporary workspace.
"""

import asyncio
from pathlib import Path

import pytest

from apps.api.database import create_tables
from apps.api.models.tool_manifest import ExecutionContext
from apps.api.skills.list_files import ListFilesTool
from apps.api.skills.read_file import ReadFileTool
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.remember_fact import RememberFactTool
from apps.api.skills.run_shell_safe import RunShellSafeTool
from apps.api.skills.search_in_files import SearchInFilesTool
from apps.api.skills.search_memory import SearchMemoryTool
from apps.api.skills.write_file import WriteFileTool


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _ctx(workspace: Path, db_path: Path | None = None) -> ExecutionContext:
    """Build an ExecutionContext for testing."""
    return ExecutionContext(
        workspace_root=str(workspace),
        session_id="test-session",
        run_id="test-run",
        db_path=str(db_path) if db_path else "",
    )


# ------------------------------------------------------------------
# Registry tests
# ------------------------------------------------------------------


class TestSkillRegistry:
    """Tests for the skill registry."""

    def test_all_seven_tools_registered(self) -> None:
        registry = SkillRegistry()
        manifests = registry.get_all_manifests()
        names = {m.name for m in manifests}
        expected = {
            "list_files", "read_file", "write_file",
            "search_in_files", "run_shell_safe",
            "remember_fact", "search_memory",
        }
        assert names == expected

    def test_get_tool_by_name(self) -> None:
        registry = SkillRegistry()
        tool = registry.get_tool("read_file")
        assert tool is not None
        assert tool.get_manifest().name == "read_file"

    def test_get_tool_unknown_returns_none(self) -> None:
        registry = SkillRegistry()
        assert registry.get_tool("nonexistent") is None

    def test_has_tool(self) -> None:
        registry = SkillRegistry()
        assert registry.has_tool("list_files")
        assert not registry.has_tool("nope")


# ------------------------------------------------------------------
# list_files
# ------------------------------------------------------------------


class TestListFiles:
    """Tests for the list_files tool."""

    @pytest.mark.asyncio
    async def test_lists_directory_contents(self, populated_workspace: Path) -> None:
        tool = ListFilesTool()
        result = await tool.execute({"path": "."}, _ctx(populated_workspace))
        assert result.status == "success"
        names = [e["name"] for e in result.output["entries"]]
        assert "README.md" in names
        assert "src" in names

    @pytest.mark.asyncio
    async def test_recursive_listing(self, populated_workspace: Path) -> None:
        tool = ListFilesTool()
        result = await tool.execute(
            {"path": ".", "recursive": True, "max_depth": 3},
            _ctx(populated_workspace),
        )
        assert result.status == "success"
        paths = [e["path"] for e in result.output["entries"]]
        # Should include nested files
        assert any("main.py" in p for p in paths)

    @pytest.mark.asyncio
    async def test_nonexistent_path_error(self, tmp_workspace: Path) -> None:
        tool = ListFilesTool()
        result = await tool.execute({"path": "nonexistent"}, _ctx(tmp_workspace))
        assert result.status == "error"
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_path_outside_workspace_error(self, tmp_workspace: Path) -> None:
        tool = ListFilesTool()
        result = await tool.execute({"path": "/etc"}, _ctx(tmp_workspace))
        assert result.status == "error"
        assert "outside workspace" in result.error.lower()


# ------------------------------------------------------------------
# read_file
# ------------------------------------------------------------------


class TestReadFile:
    """Tests for the read_file tool."""

    @pytest.mark.asyncio
    async def test_reads_text_file(self, populated_workspace: Path) -> None:
        tool = ReadFileTool()
        result = await tool.execute({"path": "README.md"}, _ctx(populated_workspace))
        assert result.status == "success"
        assert "Test Project" in result.output["content"]

    @pytest.mark.asyncio
    async def test_nonexistent_file_error(self, tmp_workspace: Path) -> None:
        tool = ReadFileTool()
        result = await tool.execute({"path": "nope.txt"}, _ctx(tmp_workspace))
        assert result.status == "error"
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_binary_file_rejected(self, tmp_workspace: Path) -> None:
        binary = tmp_workspace / "test.bin"
        binary.write_bytes(b"\x00\x01\x02\x03" * 100)
        tool = ReadFileTool()
        result = await tool.execute({"path": "test.bin"}, _ctx(tmp_workspace))
        assert result.status == "error"
        assert "binary" in result.error.lower()

    @pytest.mark.asyncio
    async def test_offset_and_limit(self, populated_workspace: Path) -> None:
        tool = ReadFileTool()
        result = await tool.execute(
            {"path": "README.md", "offset": 1, "limit": 2},
            _ctx(populated_workspace),
        )
        assert result.status == "success"
        # Should skip first line and return 2 lines
        assert "Test Project" not in result.output["content"]


# ------------------------------------------------------------------
# write_file
# ------------------------------------------------------------------


class TestWriteFile:
    """Tests for the write_file tool."""

    @pytest.mark.asyncio
    async def test_creates_new_file(self, tmp_workspace: Path) -> None:
        tool = WriteFileTool()
        result = await tool.execute(
            {"path": "new.txt", "content": "hello world", "mode": "create"},
            _ctx(tmp_workspace),
        )
        assert result.status == "success"
        assert (tmp_workspace / "new.txt").read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_create_fails_if_exists(self, tmp_workspace: Path) -> None:
        (tmp_workspace / "existing.txt").write_text("old")
        tool = WriteFileTool()
        result = await tool.execute(
            {"path": "existing.txt", "content": "new", "mode": "create"},
            _ctx(tmp_workspace),
        )
        assert result.status == "error"
        assert "already exists" in result.error.lower()

    @pytest.mark.asyncio
    async def test_overwrite_replaces_content(self, tmp_workspace: Path) -> None:
        (tmp_workspace / "overwrite.txt").write_text("old content")
        tool = WriteFileTool()
        result = await tool.execute(
            {"path": "overwrite.txt", "content": "new content", "mode": "overwrite"},
            _ctx(tmp_workspace),
        )
        assert result.status == "success"
        assert (tmp_workspace / "overwrite.txt").read_text() == "new content"

    @pytest.mark.asyncio
    async def test_append_adds_content(self, tmp_workspace: Path) -> None:
        (tmp_workspace / "append.txt").write_text("first\n")
        tool = WriteFileTool()
        result = await tool.execute(
            {"path": "append.txt", "content": "second\n", "mode": "append"},
            _ctx(tmp_workspace),
        )
        assert result.status == "success"
        assert (tmp_workspace / "append.txt").read_text() == "first\nsecond\n"

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, tmp_workspace: Path) -> None:
        tool = WriteFileTool()
        result = await tool.execute(
            {"path": "deep/nested/dir/file.txt", "content": "deep", "mode": "create"},
            _ctx(tmp_workspace),
        )
        assert result.status == "success"
        assert (tmp_workspace / "deep" / "nested" / "dir" / "file.txt").exists()

    @pytest.mark.asyncio
    async def test_path_outside_workspace_error(self, tmp_workspace: Path) -> None:
        tool = WriteFileTool()
        result = await tool.execute(
            {"path": "/etc/evil.txt", "content": "bad", "mode": "create"},
            _ctx(tmp_workspace),
        )
        assert result.status == "error"


# ------------------------------------------------------------------
# search_in_files
# ------------------------------------------------------------------


class TestSearchInFiles:
    """Tests for the search_in_files tool."""

    @pytest.mark.asyncio
    async def test_finds_known_pattern(self, populated_workspace: Path) -> None:
        tool = SearchInFilesTool()
        result = await tool.execute(
            {"path": ".", "query": "TODO"},
            _ctx(populated_workspace),
        )
        assert result.status == "success"
        assert result.output["total_matches"] >= 2

    @pytest.mark.asyncio
    async def test_no_matches(self, populated_workspace: Path) -> None:
        tool = SearchInFilesTool()
        result = await tool.execute(
            {"path": ".", "query": "ZZZZNOTFOUND"},
            _ctx(populated_workspace),
        )
        assert result.status == "success"
        assert result.output["total_matches"] == 0

    @pytest.mark.asyncio
    async def test_file_glob_filter(self, populated_workspace: Path) -> None:
        tool = SearchInFilesTool()
        result = await tool.execute(
            {"path": ".", "query": "TODO", "file_glob": "*.md"},
            _ctx(populated_workspace),
        )
        assert result.status == "success"
        # Should only find matches in .md files
        for m in result.output["matches"]:
            assert m["file"].endswith(".md")

    @pytest.mark.asyncio
    async def test_empty_query_error(self, tmp_workspace: Path) -> None:
        tool = SearchInFilesTool()
        result = await tool.execute(
            {"path": ".", "query": ""},
            _ctx(tmp_workspace),
        )
        assert result.status == "error"


# ------------------------------------------------------------------
# run_shell_safe
# ------------------------------------------------------------------


class TestRunShellSafe:
    """Tests for the run_shell_safe tool."""

    @pytest.mark.asyncio
    async def test_ls_succeeds(self, populated_workspace: Path) -> None:
        tool = RunShellSafeTool()
        result = await tool.execute(
            {"command": "ls", "args": [], "cwd": str(populated_workspace)},
            _ctx(populated_workspace),
        )
        assert result.status == "success"
        assert "README" in result.output["stdout"]

    @pytest.mark.asyncio
    async def test_pwd_succeeds(self, populated_workspace: Path) -> None:
        tool = RunShellSafeTool()
        result = await tool.execute(
            {"command": "pwd", "args": [], "cwd": str(populated_workspace)},
            _ctx(populated_workspace),
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_rm_blocked(self, populated_workspace: Path) -> None:
        tool = RunShellSafeTool()
        result = await tool.execute(
            {"command": "rm", "args": ["-rf", "/"], "cwd": str(populated_workspace)},
            _ctx(populated_workspace),
        )
        assert result.status == "error"
        assert "not in allowlist" in result.error.lower()

    @pytest.mark.asyncio
    async def test_injection_blocked(self, populated_workspace: Path) -> None:
        tool = RunShellSafeTool()
        result = await tool.execute(
            {"command": "ls", "args": ["; rm -rf /"], "cwd": str(populated_workspace)},
            _ctx(populated_workspace),
        )
        assert result.status == "error"
        assert "injection" in result.error.lower() or "metacharacter" in result.error.lower()

    @pytest.mark.asyncio
    async def test_cwd_outside_workspace_blocked(self, populated_workspace: Path) -> None:
        tool = RunShellSafeTool()
        result = await tool.execute(
            {"command": "ls", "args": [], "cwd": "/etc"},
            _ctx(populated_workspace),
        )
        assert result.status == "error"
        assert "outside workspace" in result.error.lower()

    @pytest.mark.asyncio
    async def test_cat_reads_file(self, populated_workspace: Path) -> None:
        tool = RunShellSafeTool()
        result = await tool.execute(
            {"command": "cat", "args": [str(populated_workspace / "README.md")], "cwd": str(populated_workspace)},
            _ctx(populated_workspace),
        )
        assert result.status == "success"
        assert "Test Project" in result.output["stdout"]

    @pytest.mark.asyncio
    async def test_grep_finds_pattern(self, populated_workspace: Path) -> None:
        tool = RunShellSafeTool()
        result = await tool.execute(
            {
                "command": "grep",
                "args": ["-r", "TODO", str(populated_workspace)],
                "cwd": str(populated_workspace),
            },
            _ctx(populated_workspace),
        )
        assert result.status == "success"
        assert "TODO" in result.output["stdout"]


# ------------------------------------------------------------------
# remember_fact + search_memory (require database)
# ------------------------------------------------------------------


class TestRememberFact:
    """Tests for the remember_fact tool."""

    @pytest.mark.asyncio
    async def test_stores_fact(self, tmp_workspace: Path, tmp_db_path: Path) -> None:
        await create_tables(tmp_db_path)
        tool = RememberFactTool()
        ctx = _ctx(tmp_workspace, tmp_db_path)
        result = await tool.execute(
            {"content": "User prefers dark mode", "source": "user"},
            ctx,
        )
        assert result.status == "success"
        assert result.output["memory_id"]

    @pytest.mark.asyncio
    async def test_empty_content_error(self, tmp_workspace: Path, tmp_db_path: Path) -> None:
        await create_tables(tmp_db_path)
        tool = RememberFactTool()
        ctx = _ctx(tmp_workspace, tmp_db_path)
        result = await tool.execute(
            {"content": "", "source": "user"},
            ctx,
        )
        assert result.status == "error"


class TestSearchMemory:
    """Tests for the search_memory tool."""

    @pytest.mark.asyncio
    async def test_search_finds_stored_fact(self, tmp_workspace: Path, tmp_db_path: Path) -> None:
        await create_tables(tmp_db_path)
        ctx = _ctx(tmp_workspace, tmp_db_path)

        # Store a fact first
        remember = RememberFactTool()
        await remember.execute(
            {"content": "User works on thesis project", "source": "user"},
            ctx,
        )

        # Search for it
        search = SearchMemoryTool()
        result = await search.execute({"query": "thesis"}, ctx)
        assert result.status == "success"
        assert result.output["total"] >= 1
        assert "thesis" in result.output["items"][0]["content"].lower()


# ------------------------------------------------------------------
# Argument validation
# ------------------------------------------------------------------


class TestArgValidation:
    """Tests for BaseTool.validate_args()."""

    def test_valid_args_pass(self) -> None:
        tool = ListFilesTool()
        result = tool.validate_args({"path": "/some/path"})
        assert result.valid

    def test_missing_required_arg_fails(self) -> None:
        tool = ListFilesTool()
        result = tool.validate_args({})
        assert not result.valid
        assert len(result.errors) > 0

    def test_extra_property_fails(self) -> None:
        tool = ListFilesTool()
        result = tool.validate_args({"path": "/p", "evil": True})
        assert not result.valid
