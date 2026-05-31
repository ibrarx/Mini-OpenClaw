"""Tests for named mounts — multi-directory support.

Covers config validation, policy resolution, tool-level path handling,
and read-only enforcement.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from apps.api.config import MountConfig, Settings
from apps.api.core.policy import PolicyEngine
from apps.api.skills.base import ToolContext, resolve_tool_path


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def mount_dirs(tmp_path: Path) -> dict[str, Path]:
    """Create a primary workspace and two mount directories."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "todo.md").write_text("buy milk\n")
    (notes / "sub").mkdir()
    (notes / "sub" / "deep.txt").write_text("deep\n")
    data = tmp_path / "data"
    data.mkdir()
    (data / "report.csv").write_text("a,b\n1,2\n")
    return {"workspace": ws, "notes": notes, "data": data}


@pytest.fixture
def policy_with_mounts(mount_dirs: dict[str, Path]) -> PolicyEngine:
    """PolicyEngine with primary workspace + two mounts (data is read-only)."""
    return PolicyEngine(
        workspace_root=mount_dirs["workspace"],
        mounts={
            "notes": (mount_dirs["notes"], False),
            "data": (mount_dirs["data"], True),    # read-only
        },
    )


@pytest.fixture
def context_with_mounts(mount_dirs: dict[str, Path]) -> ToolContext:
    """ToolContext with mounts matching the policy fixture."""
    return ToolContext(
        workspace_root=str(mount_dirs["workspace"]),
        mounts={
            "notes": (str(mount_dirs["notes"]), False),
            "data": (str(mount_dirs["data"]), True),
        },
        run_id="test_run",
        step_id="test_step",
    )


# ── Config validation ────────────────────────────────────────────

class TestMountConfig:
    def test_valid_mount_names(self) -> None:
        s = Settings(
            workspace_mounts=[
                MountConfig(name="notes", path=Path("/tmp/notes")),
                MountConfig(name="data_2", path=Path("/tmp/data")),
            ],
        )
        assert len(s.workspace_mounts) == 2

    def test_duplicate_mount_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="Duplicate mount name"):
            Settings(
                workspace_mounts=[
                    MountConfig(name="notes", path=Path("/tmp/a")),
                    MountConfig(name="notes", path=Path("/tmp/b")),
                ],
            )

    def test_reserved_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            Settings(
                workspace_mounts=[
                    MountConfig(name="workspace", path=Path("/tmp/a")),
                ],
            )

    def test_invalid_characters_rejected(self) -> None:
        with pytest.raises(ValueError, match="alphanumeric"):
            Settings(
                workspace_mounts=[
                    MountConfig(name="bad/name", path=Path("/tmp/a")),
                ],
            )

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="alphanumeric"):
            Settings(
                workspace_mounts=[
                    MountConfig(name="", path=Path("/tmp/a")),
                ],
            )

    def test_resolved_mounts_property(self, tmp_path: Path) -> None:
        d = tmp_path / "m"
        d.mkdir()
        s = Settings(
            workspace_mounts=[
                MountConfig(name="mydir", path=d, read_only=True),
            ],
        )
        mounts = s.resolved_mounts
        assert "mydir" in mounts
        assert mounts["mydir"][0] == d.resolve()
        assert mounts["mydir"][1] is True


# ── Policy engine: resolve_root ──────────────────────────────────

class TestPolicyResolveRoot:
    def test_unprefixed_resolves_to_primary(
        self, policy_with_mounts: PolicyEngine, mount_dirs: dict[str, Path]
    ) -> None:
        root, target, ro = policy_with_mounts.resolve_root("file.txt")
        assert root == mount_dirs["workspace"].resolve()
        assert not ro

    def test_known_alias_resolves_to_mount(
        self, policy_with_mounts: PolicyEngine, mount_dirs: dict[str, Path]
    ) -> None:
        root, target, ro = policy_with_mounts.resolve_root("notes:todo.md")
        assert root == mount_dirs["notes"].resolve()
        assert target == (mount_dirs["notes"] / "todo.md").resolve()
        assert not ro

    def test_read_only_mount_flag(
        self, policy_with_mounts: PolicyEngine, mount_dirs: dict[str, Path]
    ) -> None:
        root, target, ro = policy_with_mounts.resolve_root("data:report.csv")
        assert root == mount_dirs["data"].resolve()
        assert ro is True

    def test_unknown_alias_raises(self, policy_with_mounts: PolicyEngine) -> None:
        with pytest.raises(ValueError, match="Unknown mount alias"):
            policy_with_mounts.resolve_root("bogus:file.txt")


# ── Policy engine: validate_path with mounts ─────────────────────

class TestPolicyValidatePathMounts:
    def test_unprefixed_still_works(self, policy_with_mounts: PolicyEngine) -> None:
        r = policy_with_mounts.validate_path("file.txt")
        assert r.allowed
        assert r.classification == "safe"

    def test_mount_read_allowed(self, policy_with_mounts: PolicyEngine) -> None:
        r = policy_with_mounts.validate_path("notes:todo.md")
        assert r.allowed

    def test_mount_traversal_blocked(self, policy_with_mounts: PolicyEngine) -> None:
        r = policy_with_mounts.validate_path("notes:../escape")
        assert not r.allowed
        assert r.classification == "forbidden"

    def test_read_only_mount_read_allowed(self, policy_with_mounts: PolicyEngine) -> None:
        r = policy_with_mounts.validate_path("data:report.csv", write=False)
        assert r.allowed

    def test_read_only_mount_write_forbidden(self, policy_with_mounts: PolicyEngine) -> None:
        r = policy_with_mounts.validate_path("data:report.csv", write=True)
        assert not r.allowed
        assert "read-only" in r.reason.lower()

    def test_writable_mount_write_requires_approval(
        self, policy_with_mounts: PolicyEngine
    ) -> None:
        r = policy_with_mounts.validate_path("notes:todo.md", write=True)
        assert r.allowed
        assert r.classification == "approval_required"

    def test_unknown_alias_forbidden(self, policy_with_mounts: PolicyEngine) -> None:
        r = policy_with_mounts.validate_path("nope:file.txt")
        assert not r.allowed
        assert r.classification == "forbidden"


# ── resolve_tool_path ────────────────────────────────────────────

class TestResolveToolPath:
    def test_unprefixed(
        self, context_with_mounts: ToolContext, mount_dirs: dict[str, Path]
    ) -> None:
        root, target = resolve_tool_path("file.txt", context_with_mounts)
        assert root == mount_dirs["workspace"].resolve()

    def test_mount_prefix(
        self, context_with_mounts: ToolContext, mount_dirs: dict[str, Path]
    ) -> None:
        root, target = resolve_tool_path("notes:todo.md", context_with_mounts)
        assert root == mount_dirs["notes"].resolve()
        assert target == (mount_dirs["notes"] / "todo.md").resolve()

    def test_traversal_raises(self, context_with_mounts: ToolContext) -> None:
        with pytest.raises(ValueError):
            resolve_tool_path("notes:../escape", context_with_mounts)

    def test_unknown_alias_raises(self, context_with_mounts: ToolContext) -> None:
        with pytest.raises(ValueError, match="Unknown mount alias"):
            resolve_tool_path("bogus:file.txt", context_with_mounts)


# ── Tool-level integration ───────────────────────────────────────

class TestToolsWithMounts:
    @pytest.fixture
    def ctx(self, context_with_mounts: ToolContext) -> ToolContext:
        return context_with_mounts

    @pytest.mark.asyncio
    async def test_read_file_from_mount(self, ctx: ToolContext) -> None:
        from apps.api.skills.read_file import ReadFileTool
        tool = ReadFileTool()
        result = await tool.execute({"path": "notes:todo.md"}, ctx)
        assert result.status == "success"
        assert "buy milk" in result.output["content"]

    @pytest.mark.asyncio
    async def test_list_files_in_mount(self, ctx: ToolContext) -> None:
        from apps.api.skills.list_files import ListFilesTool
        tool = ListFilesTool()
        result = await tool.execute({"path": "notes:."}, ctx)
        assert result.status == "success"
        names = [e["name"] for e in result.output["entries"]]
        assert "todo.md" in names

    @pytest.mark.asyncio
    async def test_search_in_mount(self, ctx: ToolContext) -> None:
        from apps.api.skills.search_in_files import SearchInFilesTool
        tool = SearchInFilesTool()
        result = await tool.execute({"path": "notes:.", "query": "milk"}, ctx)
        assert result.status == "success"
        assert result.output["total"] >= 1

    @pytest.mark.asyncio
    async def test_write_file_read_only_mount_blocked_by_policy(
        self, policy_with_mounts: PolicyEngine
    ) -> None:
        """Write to a read-only mount is blocked at the policy layer."""
        r = policy_with_mounts.validate_path("data:new.csv", write=True)
        assert not r.allowed

    @pytest.mark.asyncio
    async def test_read_file_traversal_from_mount(self, ctx: ToolContext) -> None:
        from apps.api.skills.read_file import ReadFileTool
        tool = ReadFileTool()
        result = await tool.execute({"path": "notes:../escape.txt"}, ctx)
        assert result.status == "error"


# ── Backward compatibility (single-workspace, no mounts) ────────

class TestBackwardCompat:
    """Ensure PolicyEngine works identically with no mounts (existing behavior)."""

    def test_single_arg_constructor(self, tmp_workspace: Path) -> None:
        p = PolicyEngine(workspace_root=tmp_workspace)
        assert p.workspace_root == tmp_workspace.resolve()
        assert p.mounts == {}

    def test_path_validation_unchanged(self, tmp_workspace: Path) -> None:
        p = PolicyEngine(workspace_root=tmp_workspace)
        assert p.validate_path("file.txt").allowed
        assert not p.validate_path("/etc/passwd").allowed
        assert not p.validate_path("../escape").allowed

    def test_write_classification_unchanged(self, tmp_workspace: Path) -> None:
        p = PolicyEngine(workspace_root=tmp_workspace)
        r = p.validate_path("file.txt", write=True)
        assert r.allowed
        assert r.classification == "approval_required"

    def test_tool_context_no_mounts_default(self, tmp_workspace: Path) -> None:
        ctx = ToolContext(workspace_root=str(tmp_workspace))
        assert ctx.mounts == {}
        # resolve_tool_path should work with empty mounts
        root, target = resolve_tool_path("file.txt", ctx)
        assert root == tmp_workspace.resolve()
