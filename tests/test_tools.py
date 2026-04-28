"""Tests for V1 tool implementations."""
from pathlib import Path

import pytest

from apps.api.database import create_tables
from apps.api.skills.base import ToolContext
from apps.api.skills.list_files import ListFilesTool
from apps.api.skills.read_file import ReadFileTool
from apps.api.skills.write_file import WriteFileTool
from apps.api.skills.search_in_files import SearchInFilesTool
from apps.api.skills.run_shell_safe import RunShellSafeTool
from apps.api.skills.remember_fact import RememberFactTool
from apps.api.skills.search_memory import SearchMemoryTool
from apps.api.skills.registry import SkillRegistry


def _ctx(workspace: Path, db_path: Path | None = None) -> ToolContext:
    return ToolContext(
        workspace_root=str(workspace),
        run_id="test_run",
        step_id="test_step",
        db_path=str(db_path) if db_path else "",
    )


# ── Registry ─────────────────────────────────────────────────────


class TestRegistry:
    def test_all_seven_registered(self) -> None:
        r = SkillRegistry()
        r.discover()
        assert r.tool_count == 7

    def test_get_known_tool(self) -> None:
        r = SkillRegistry()
        r.discover()
        assert r.get("read_file") is not None

    def test_get_unknown_tool_returns_none(self) -> None:
        r = SkillRegistry()
        r.discover()
        assert r.get("nope") is None

    def test_list_manifests(self) -> None:
        r = SkillRegistry()
        r.discover()
        manifests = r.list_manifests()
        names = {m.name for m in manifests}
        assert "list_files" in names
        assert "write_file" in names
        assert len(manifests) == 7

    def test_planner_descriptions(self) -> None:
        r = SkillRegistry()
        r.discover()
        descs = r.get_planner_descriptions()
        assert len(descs) == 7
        assert all("name" in d and "description" in d for d in descs)


# ── list_files ───────────────────────────────────────────────────


class TestListFiles:
    @pytest.mark.asyncio
    async def test_lists_workspace(self, populated_workspace: Path) -> None:
        r = await ListFilesTool().execute({"path": "."}, _ctx(populated_workspace))
        assert r.status == "success"
        names = [e["name"] for e in r.output["entries"]]
        assert "README.md" in names

    @pytest.mark.asyncio
    async def test_recursive(self, populated_workspace: Path) -> None:
        r = await ListFilesTool().execute(
            {"path": ".", "recursive": True, "max_depth": 3},
            _ctx(populated_workspace),
        )
        assert r.status == "success"
        paths = [e["path"] for e in r.output["entries"]]
        assert any("main.py" in p for p in paths)

    @pytest.mark.asyncio
    async def test_nonexistent_path_error(self, tmp_workspace: Path) -> None:
        r = await ListFilesTool().execute({"path": "nope"}, _ctx(tmp_workspace))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_outside_workspace_error(self, tmp_workspace: Path) -> None:
        r = await ListFilesTool().execute({"path": "/etc"}, _ctx(tmp_workspace))
        assert r.status == "error"


# ── read_file ────────────────────────────────────────────────────


class TestReadFile:
    @pytest.mark.asyncio
    async def test_reads_text_file(self, populated_workspace: Path) -> None:
        r = await ReadFileTool().execute({"path": "README.md"}, _ctx(populated_workspace))
        assert r.status == "success"
        assert "Test Project" in r.output["content"]

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_workspace: Path) -> None:
        r = await ReadFileTool().execute({"path": "nope.txt"}, _ctx(tmp_workspace))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_binary_file_rejected(self, tmp_workspace: Path) -> None:
        (tmp_workspace / "b.bin").write_bytes(b"\x00\x01\x02" * 100)
        r = await ReadFileTool().execute({"path": "b.bin"}, _ctx(tmp_workspace))
        assert r.status == "error"
        assert "binary" in r.error.lower()

    @pytest.mark.asyncio
    async def test_outside_workspace(self, tmp_workspace: Path) -> None:
        r = await ReadFileTool().execute({"path": "/etc/passwd"}, _ctx(tmp_workspace))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_offset_and_limit(self, populated_workspace: Path) -> None:
        r = await ReadFileTool().execute(
            {"path": "README.md", "offset": 1, "limit": 2},
            _ctx(populated_workspace),
        )
        assert r.status == "success"
        # Should have at most 2 lines starting from offset 1
        lines = r.output["content"].split("\n")
        assert len(lines) <= 2


# ── write_file ───────────────────────────────────────────────────


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_create_new_file(self, tmp_workspace: Path) -> None:
        r = await WriteFileTool().execute(
            {"path": "new.txt", "content": "hello", "mode": "create"},
            _ctx(tmp_workspace),
        )
        assert r.status == "success"
        assert (tmp_workspace / "new.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_create_existing_file_error(self, tmp_workspace: Path) -> None:
        (tmp_workspace / "x.txt").write_text("old")
        r = await WriteFileTool().execute(
            {"path": "x.txt", "content": "new", "mode": "create"},
            _ctx(tmp_workspace),
        )
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_overwrite(self, tmp_workspace: Path) -> None:
        (tmp_workspace / "x.txt").write_text("old")
        r = await WriteFileTool().execute(
            {"path": "x.txt", "content": "new", "mode": "overwrite"},
            _ctx(tmp_workspace),
        )
        assert r.status == "success"
        assert (tmp_workspace / "x.txt").read_text() == "new"

    @pytest.mark.asyncio
    async def test_append(self, tmp_workspace: Path) -> None:
        (tmp_workspace / "x.txt").write_text("a")
        r = await WriteFileTool().execute(
            {"path": "x.txt", "content": "b", "mode": "append"},
            _ctx(tmp_workspace),
        )
        assert r.status == "success"
        assert (tmp_workspace / "x.txt").read_text() == "ab"

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_workspace: Path) -> None:
        r = await WriteFileTool().execute(
            {"path": "d/e/f.txt", "content": "deep", "mode": "create"},
            _ctx(tmp_workspace),
        )
        assert r.status == "success"
        assert (tmp_workspace / "d" / "e" / "f.txt").exists()

    @pytest.mark.asyncio
    async def test_outside_workspace_error(self, tmp_workspace: Path) -> None:
        r = await WriteFileTool().execute(
            {"path": "/etc/evil", "content": "x", "mode": "create"},
            _ctx(tmp_workspace),
        )
        assert r.status == "error"


# ── search_in_files ──────────────────────────────────────────────


class TestSearchInFiles:
    @pytest.mark.asyncio
    async def test_finds_matches(self, populated_workspace: Path) -> None:
        r = await SearchInFilesTool().execute(
            {"path": ".", "query": "TODO"},
            _ctx(populated_workspace),
        )
        assert r.status == "success"
        assert r.output["total"] >= 2

    @pytest.mark.asyncio
    async def test_no_match(self, populated_workspace: Path) -> None:
        r = await SearchInFilesTool().execute(
            {"path": ".", "query": "ZZZZZ"},
            _ctx(populated_workspace),
        )
        assert r.status == "success"
        assert r.output["total"] == 0

    @pytest.mark.asyncio
    async def test_file_glob_filter(self, populated_workspace: Path) -> None:
        r = await SearchInFilesTool().execute(
            {"path": ".", "query": "TODO", "file_glob": "*.md"},
            _ctx(populated_workspace),
        )
        assert r.status == "success"
        assert all(m["file"].endswith(".md") for m in r.output["matches"])


# ── run_shell_safe ───────────────────────────────────────────────


class TestRunShellSafe:
    @pytest.mark.asyncio
    async def test_ls_succeeds(self, populated_workspace: Path) -> None:
        r = await RunShellSafeTool().execute(
            {"command": "ls", "args": [], "cwd": "."},
            _ctx(populated_workspace),
        )
        assert r.status == "success"
        assert "README" in r.output["stdout"]

    @pytest.mark.asyncio
    async def test_disallowed_command_error(self, populated_workspace: Path) -> None:
        r = await RunShellSafeTool().execute(
            {"command": "rm", "args": ["-rf", "/"], "cwd": "."},
            _ctx(populated_workspace),
        )
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_injection_in_args(self, populated_workspace: Path) -> None:
        r = await RunShellSafeTool().execute(
            {"command": "ls", "args": ["; rm -rf /"], "cwd": "."},
            _ctx(populated_workspace),
        )
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_cwd_outside_workspace(self, populated_workspace: Path) -> None:
        r = await RunShellSafeTool().execute(
            {"command": "ls", "args": [], "cwd": "/etc"},
            _ctx(populated_workspace),
        )
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_pwd(self, populated_workspace: Path) -> None:
        r = await RunShellSafeTool().execute(
            {"command": "pwd", "args": [], "cwd": "."},
            _ctx(populated_workspace),
        )
        assert r.status == "success"


# ── remember_fact ────────────────────────────────────────────────


class TestRememberFact:
    @pytest.mark.asyncio
    async def test_stores_fact(self, tmp_workspace: Path, tmp_db_path: Path) -> None:
        await create_tables(tmp_db_path)
        r = await RememberFactTool().execute(
            {"content": "dark mode", "source": "user"},
            _ctx(tmp_workspace, tmp_db_path),
        )
        assert r.status == "success"
        assert r.output["memory_id"]

    @pytest.mark.asyncio
    async def test_empty_content_error(self, tmp_workspace: Path, tmp_db_path: Path) -> None:
        await create_tables(tmp_db_path)
        r = await RememberFactTool().execute(
            {"content": "", "source": "user"},
            _ctx(tmp_workspace, tmp_db_path),
        )
        assert r.status == "error"


# ── search_memory ────────────────────────────────────────────────


class TestSearchMemory:
    @pytest.mark.asyncio
    async def test_finds_stored_fact(self, tmp_workspace: Path, tmp_db_path: Path) -> None:
        await create_tables(tmp_db_path)
        ctx = _ctx(tmp_workspace, tmp_db_path)
        # Store, then search
        await RememberFactTool().execute(
            {"content": "thesis project", "source": "user"}, ctx
        )
        r = await SearchMemoryTool().execute({"query": "thesis"}, ctx)
        assert r.status == "success"
        assert r.output["total"] >= 1

    @pytest.mark.asyncio
    async def test_no_matches_empty(self, tmp_workspace: Path, tmp_db_path: Path) -> None:
        await create_tables(tmp_db_path)
        r = await SearchMemoryTool().execute(
            {"query": "nonexistent_xyz"},
            _ctx(tmp_workspace, tmp_db_path),
        )
        assert r.status == "success"
        assert r.output["total"] == 0

    @pytest.mark.asyncio
    async def test_empty_query_error(self, tmp_workspace: Path, tmp_db_path: Path) -> None:
        await create_tables(tmp_db_path)
        r = await SearchMemoryTool().execute(
            {"query": ""},
            _ctx(tmp_workspace, tmp_db_path),
        )
        assert r.status == "error"
