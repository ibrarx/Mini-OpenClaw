"""Tests for V1 tool implementations."""
import asyncio
from pathlib import Path
import pytest
from apps.api.database import create_tables
from apps.api.skills.list_files import ListFilesTool
from apps.api.skills.read_file import ReadFileTool
from apps.api.skills.write_file import WriteFileTool
from apps.api.skills.search_in_files import SearchInFilesTool
from apps.api.skills.run_shell_safe import RunShellSafeTool
from apps.api.skills.remember_fact import RememberFactTool
from apps.api.skills.search_memory import SearchMemoryTool
from apps.api.skills.registry import SkillRegistry

def _ctx(workspace: Path, db=None) -> dict:
    return {"workspace_root": str(workspace), "session_id": "test", "run_id": "test", "db": db}

class TestRegistry:
    def test_all_seven(self):
        r = SkillRegistry(); r.discover()
        assert len(r.get_tool_names()) == 7
    def test_get_tool(self):
        r = SkillRegistry(); r.discover()
        assert r.get_tool("read_file") is not None
    def test_unknown(self):
        r = SkillRegistry(); r.discover()
        assert r.get_tool("nope") is None

class TestListFiles:
    @pytest.mark.asyncio
    async def test_lists(self, populated_workspace):
        t = ListFilesTool()
        r = await t.execute({"path":"."}, _ctx(populated_workspace))
        assert r.status == "success"
        assert any(e["name"] == "README.md" for e in r.output["entries"])

    @pytest.mark.asyncio
    async def test_recursive(self, populated_workspace):
        r = await ListFilesTool().execute({"path":".","recursive":True,"max_depth":3}, _ctx(populated_workspace))
        assert r.status == "success"
        assert any("main.py" in e["path"] for e in r.output["entries"])

    @pytest.mark.asyncio
    async def test_not_found(self, tmp_workspace):
        r = await ListFilesTool().execute({"path":"nope"}, _ctx(tmp_workspace))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_outside(self, tmp_workspace):
        r = await ListFilesTool().execute({"path":"/etc"}, _ctx(tmp_workspace))
        assert r.status == "error"

class TestReadFile:
    @pytest.mark.asyncio
    async def test_reads(self, populated_workspace):
        r = await ReadFileTool().execute({"path":"README.md"}, _ctx(populated_workspace))
        assert r.status == "success" and "Test Project" in r.output["content"]

    @pytest.mark.asyncio
    async def test_not_found(self, tmp_workspace):
        r = await ReadFileTool().execute({"path":"nope.txt"}, _ctx(tmp_workspace))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_binary(self, tmp_workspace):
        (tmp_workspace/"b.bin").write_bytes(b"\x00"*100)
        r = await ReadFileTool().execute({"path":"b.bin"}, _ctx(tmp_workspace))
        assert r.status == "error" and "binary" in r.error.lower()

class TestWriteFile:
    @pytest.mark.asyncio
    async def test_create(self, tmp_workspace):
        r = await WriteFileTool().execute({"path":"new.txt","content":"hello","mode":"create"}, _ctx(tmp_workspace))
        assert r.status == "success" and (tmp_workspace/"new.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_create_exists(self, tmp_workspace):
        (tmp_workspace/"x.txt").write_text("old")
        r = await WriteFileTool().execute({"path":"x.txt","content":"new","mode":"create"}, _ctx(tmp_workspace))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_overwrite(self, tmp_workspace):
        (tmp_workspace/"x.txt").write_text("old")
        r = await WriteFileTool().execute({"path":"x.txt","content":"new","mode":"overwrite"}, _ctx(tmp_workspace))
        assert r.status == "success" and (tmp_workspace/"x.txt").read_text() == "new"

    @pytest.mark.asyncio
    async def test_append(self, tmp_workspace):
        (tmp_workspace/"x.txt").write_text("a")
        r = await WriteFileTool().execute({"path":"x.txt","content":"b","mode":"append"}, _ctx(tmp_workspace))
        assert r.status == "success" and (tmp_workspace/"x.txt").read_text() == "ab"

    @pytest.mark.asyncio
    async def test_parent_dirs(self, tmp_workspace):
        r = await WriteFileTool().execute({"path":"d/e/f.txt","content":"deep","mode":"create"}, _ctx(tmp_workspace))
        assert r.status == "success" and (tmp_workspace/"d"/"e"/"f.txt").exists()

    @pytest.mark.asyncio
    async def test_outside(self, tmp_workspace):
        r = await WriteFileTool().execute({"path":"/etc/evil","content":"x","mode":"create"}, _ctx(tmp_workspace))
        assert r.status == "error"

class TestSearchInFiles:
    @pytest.mark.asyncio
    async def test_finds(self, populated_workspace):
        r = await SearchInFilesTool().execute({"path":".","query":"TODO"}, _ctx(populated_workspace))
        assert r.status == "success" and r.output["total_matches"] >= 2

    @pytest.mark.asyncio
    async def test_no_match(self, populated_workspace):
        r = await SearchInFilesTool().execute({"path":".","query":"ZZZZZ"}, _ctx(populated_workspace))
        assert r.status == "success" and r.output["total_matches"] == 0

    @pytest.mark.asyncio
    async def test_glob(self, populated_workspace):
        r = await SearchInFilesTool().execute({"path":".","query":"TODO","file_glob":"*.md"}, _ctx(populated_workspace))
        assert all(m["file"].endswith(".md") for m in r.output["matches"])

class TestRunShellSafe:
    @pytest.mark.asyncio
    async def test_ls(self, populated_workspace):
        r = await RunShellSafeTool().execute({"command":"ls","args":[],"cwd":str(populated_workspace)}, _ctx(populated_workspace))
        assert r.status == "success" and "README" in r.output["stdout"]

    @pytest.mark.asyncio
    async def test_rm_blocked(self, populated_workspace):
        r = await RunShellSafeTool().execute({"command":"rm","args":["-rf","/"],"cwd":str(populated_workspace)}, _ctx(populated_workspace))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_injection(self, populated_workspace):
        r = await RunShellSafeTool().execute({"command":"ls","args":["; rm -rf /"],"cwd":str(populated_workspace)}, _ctx(populated_workspace))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_cwd_outside(self, populated_workspace):
        r = await RunShellSafeTool().execute({"command":"ls","args":[],"cwd":"/etc"}, _ctx(populated_workspace))
        assert r.status == "error"

class TestRememberFact:
    @pytest.mark.asyncio
    async def test_stores(self, tmp_workspace, tmp_db_path):
        await create_tables(tmp_db_path)
        import aiosqlite
        async with aiosqlite.connect(str(tmp_db_path)) as db:
            db.row_factory = aiosqlite.Row
            r = await RememberFactTool().execute({"content":"dark mode","source":"user"}, _ctx(tmp_workspace, db))
            assert r.status == "success"

    @pytest.mark.asyncio
    async def test_empty(self, tmp_workspace, tmp_db_path):
        await create_tables(tmp_db_path)
        import aiosqlite
        async with aiosqlite.connect(str(tmp_db_path)) as db:
            r = await RememberFactTool().execute({"content":"","source":"user"}, _ctx(tmp_workspace, db))
            assert r.status == "error"

class TestSearchMemory:
    @pytest.mark.asyncio
    async def test_finds_stored(self, tmp_workspace, tmp_db_path):
        await create_tables(tmp_db_path)
        import aiosqlite
        async with aiosqlite.connect(str(tmp_db_path)) as db:
            db.row_factory = aiosqlite.Row
            await RememberFactTool().execute({"content":"thesis project","source":"user"}, _ctx(tmp_workspace, db))
            r = await SearchMemoryTool().execute({"query":"thesis"}, _ctx(tmp_workspace, db))
            assert r.status == "success" and r.output["total"] >= 1

class TestArgValidation:
    def test_valid(self):
        assert ListFilesTool.validate_args({"path":"/"}).valid
    def test_missing(self):
        assert not ListFilesTool.validate_args({}).valid
    def test_extra(self):
        assert not ListFilesTool.validate_args({"path":"/","evil":True}).valid
