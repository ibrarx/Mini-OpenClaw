"""
Tests for the policy engine.

Covers path validation, shell command allowlisting, injection blocking,
and cross-platform path handling.
"""

from pathlib import Path

import pytest

from apps.api.core.policy import PolicyEngine


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def policy(tmp_workspace: Path) -> PolicyEngine:
    """Create a PolicyEngine rooted at a temp workspace."""
    return PolicyEngine(workspace_root=str(tmp_workspace))


# ------------------------------------------------------------------
# Path validation
# ------------------------------------------------------------------


class TestValidatePath:
    """Tests for PolicyEngine.validate_path()."""

    def test_path_inside_workspace_allowed(self, policy: PolicyEngine, tmp_workspace: Path) -> None:
        test_file = tmp_workspace / "readme.md"
        test_file.touch()
        result = policy.validate_path(str(test_file))
        assert result.allowed

    def test_relative_path_inside_workspace(self, policy: PolicyEngine) -> None:
        result = policy.validate_path("subdir/file.txt")
        assert result.allowed

    def test_path_outside_workspace_denied(self, policy: PolicyEngine) -> None:
        result = policy.validate_path("/etc/passwd")
        assert not result.allowed
        assert "outside workspace" in result.reason.lower()

    def test_path_traversal_denied(self, policy: PolicyEngine) -> None:
        result = policy.validate_path("../../../etc/passwd")
        assert not result.allowed
        assert "traversal" in result.reason.lower()

    def test_dot_ssh_blocked(self, policy: PolicyEngine, tmp_workspace: Path) -> None:
        ssh_dir = tmp_workspace / ".ssh"
        ssh_dir.mkdir()
        result = policy.validate_path(str(ssh_dir / "id_rsa"))
        assert not result.allowed
        assert "blocked directory" in result.reason.lower()

    def test_dot_aws_blocked(self, policy: PolicyEngine, tmp_workspace: Path) -> None:
        aws_dir = tmp_workspace / ".aws"
        aws_dir.mkdir()
        result = policy.validate_path(str(aws_dir / "credentials"))
        assert not result.allowed

    def test_empty_path_denied(self, policy: PolicyEngine) -> None:
        result = policy.validate_path("")
        assert not result.allowed

    def test_home_expansion_outside_workspace(self, policy: PolicyEngine) -> None:
        result = policy.validate_path("~/secret.txt")
        assert not result.allowed

    def test_windows_backslash_path(self, policy: PolicyEngine) -> None:
        result = policy.validate_path("subdir\\file.txt")
        assert result.allowed


# ------------------------------------------------------------------
# Shell validation
# ------------------------------------------------------------------


class TestValidateShell:
    """Tests for PolicyEngine.validate_shell()."""

    def test_allowed_command_ls(self, policy: PolicyEngine, tmp_workspace: Path) -> None:
        result = policy.validate_shell("ls", [str(tmp_workspace)])
        assert result.allowed

    def test_allowed_command_pwd(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("pwd", [])
        assert result.allowed

    def test_allowed_command_grep(self, policy: PolicyEngine, tmp_workspace: Path) -> None:
        result = policy.validate_shell("grep", ["TODO", str(tmp_workspace)])
        assert result.allowed

    def test_disallowed_command_rm(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("rm", ["-rf", "/"])
        assert not result.allowed
        assert "not in allowlist" in result.reason.lower()

    def test_disallowed_command_curl(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("curl", ["http://evil.com"])
        assert not result.allowed

    def test_semicolon_injection(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("ls", ["; rm -rf /"])
        assert not result.allowed

    def test_pipe_injection(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("ls", ["| cat /etc/passwd"])
        assert not result.allowed

    def test_double_ampersand_injection(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("ls", ["&& rm -rf /"])
        assert not result.allowed

    def test_backtick_injection(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("ls", ["`whoami`"])
        assert not result.allowed

    def test_dollar_paren_injection(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("ls", ["$(cat /etc/passwd)"])
        assert not result.allowed

    def test_redirect_injection(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("ls", ["> /tmp/output"])
        assert not result.allowed

    def test_path_outside_workspace_in_arg(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("cat", ["/etc/passwd"])
        assert not result.allowed

    def test_or_injection(self, policy: PolicyEngine) -> None:
        result = policy.validate_shell("ls", ["|| echo pwned"])
        assert not result.allowed


# ------------------------------------------------------------------
# Step validation
# ------------------------------------------------------------------


class TestValidateStep:
    """Tests for PolicyEngine.validate_step()."""

    def test_safe_tool_no_approval(self, policy: PolicyEngine, tmp_workspace: Path) -> None:
        decision = policy.validate_step("list_files", {"path": str(tmp_workspace)})
        assert decision.allowed
        assert not decision.requires_approval

    def test_write_file_requires_approval(self, policy: PolicyEngine) -> None:
        decision = policy.validate_step(
            "write_file",
            {"path": "test.txt", "content": "hello", "mode": "create"},
        )
        assert decision.allowed
        assert decision.requires_approval

    def test_shell_requires_approval(self, policy: PolicyEngine) -> None:
        decision = policy.validate_step(
            "run_shell_safe",
            {"command": "pwd", "args": [], "cwd": ""},
        )
        assert decision.allowed
        assert decision.requires_approval

    def test_unknown_tool_denied(self, policy: PolicyEngine) -> None:
        decision = policy.validate_step("hack_the_planet", {"target": "everything"})
        assert not decision.allowed

    def test_memory_tools_safe(self, policy: PolicyEngine) -> None:
        for tool in ("remember_fact", "search_memory"):
            decision = policy.validate_step(tool, {"content": "test"})
            assert decision.allowed
            assert not decision.requires_approval

    def test_write_file_outside_workspace_denied(self, policy: PolicyEngine) -> None:
        decision = policy.validate_step(
            "write_file",
            {"path": "/etc/evil.txt", "content": "pwned", "mode": "create"},
        )
        assert not decision.allowed


# ------------------------------------------------------------------
# Risk classification
# ------------------------------------------------------------------


class TestClassifyRisk:
    """Tests for PolicyEngine.classify_risk()."""

    def test_safe_tool(self, policy: PolicyEngine) -> None:
        assert policy.classify_risk("list_files") == "safe"
        assert policy.classify_risk("read_file") == "safe"
        assert policy.classify_risk("search_memory") == "safe"

    def test_medium_write(self, policy: PolicyEngine) -> None:
        assert policy.classify_risk("write_file", {"mode": "create"}) == "medium"

    def test_high_overwrite(self, policy: PolicyEngine) -> None:
        assert policy.classify_risk("write_file", {"mode": "overwrite"}) == "high"

    def test_shell_medium(self, policy: PolicyEngine) -> None:
        assert policy.classify_risk("run_shell_safe") == "medium"
