"""Tests for the policy engine — validate_path, validate_shell, classify_tool."""
from pathlib import Path

import pytest

from apps.api.core.policy import PolicyEngine


@pytest.fixture
def policy(tmp_workspace: Path) -> PolicyEngine:
    return PolicyEngine(workspace_root=tmp_workspace)


# ── Path validation ──────────────────────────────────────────────


class TestValidatePath:
    def test_relative_path_inside_workspace_allowed(self, policy: PolicyEngine) -> None:
        r = policy.validate_path("subdir/file.txt")
        assert r.allowed

    def test_dot_path_allowed(self, policy: PolicyEngine) -> None:
        r = policy.validate_path(".")
        assert r.allowed

    def test_outside_workspace_denied(self, policy: PolicyEngine) -> None:
        r = policy.validate_path("/etc/passwd")
        assert not r.allowed
        assert r.classification == "forbidden"

    def test_traversal_denied(self, policy: PolicyEngine) -> None:
        r = policy.validate_path("../../../etc/passwd")
        assert not r.allowed

    def test_tilde_home_denied(self, policy: PolicyEngine) -> None:
        r = policy.validate_path("~/secret.txt")
        assert not r.allowed

    def test_empty_path_denied(self, policy: PolicyEngine) -> None:
        r = policy.validate_path("")
        assert not r.allowed

    def test_whitespace_only_denied(self, policy: PolicyEngine) -> None:
        r = policy.validate_path("   ")
        assert not r.allowed

    def test_write_requires_approval(self, policy: PolicyEngine) -> None:
        r = policy.validate_path("file.txt", write=True)
        assert r.allowed
        assert r.classification == "approval_required"

    def test_read_is_safe(self, policy: PolicyEngine) -> None:
        r = policy.validate_path("file.txt", write=False)
        assert r.allowed
        assert r.classification == "safe"

    def test_backslash_path_normalises(self, policy: PolicyEngine) -> None:
        """Backslash paths should normalise correctly (cross-platform)."""
        r = policy.validate_path("subdir\\file.txt")
        assert r.allowed

    def test_path_home_not_hardcoded(self, policy: PolicyEngine) -> None:
        """Workspace root uses Path objects, not hardcoded prefixes."""
        assert isinstance(policy.workspace_root, Path)


# ── Shell validation ─────────────────────────────────────────────


class TestValidateShell:
    @pytest.mark.parametrize("cmd", ["pwd", "ls", "find", "cat", "grep"])
    def test_allowed_commands(self, policy: PolicyEngine, cmd: str) -> None:
        r = policy.validate_shell(cmd, [])
        assert r.allowed

    @pytest.mark.parametrize("cmd", ["rm", "mv", "wget", "curl", "python", "node", "sudo"])
    def test_disallowed_commands(self, policy: PolicyEngine, cmd: str) -> None:
        r = policy.validate_shell(cmd, ["-rf", "/"])
        assert not r.allowed
        assert r.classification == "forbidden"

    def test_empty_command_denied(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("", [])
        assert not r.allowed

    def test_empty_args_handled(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("pwd", [])
        assert r.allowed

    def test_semicolon_injection(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("ls", ["; rm -rf /"])
        assert not r.allowed

    def test_double_ampersand_injection(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("ls", ["&& rm -rf /"])
        assert not r.allowed

    def test_pipe_injection(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("ls", ["| cat /etc/passwd"])
        assert not r.allowed

    def test_backtick_injection(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("ls", ["`whoami`"])
        assert not r.allowed

    def test_dollar_paren_injection(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("ls", ["$(cat /etc/passwd)"])
        assert not r.allowed

    def test_redirect_blocked(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("ls", ["> /tmp/out"])
        assert not r.allowed

    def test_traversal_in_args(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("cat", ["../../etc/passwd"])
        assert not r.allowed

    # Cross-platform: Windows metacharacters blocked on all platforms
    def test_windows_ampersand_blocked(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("ls", ["& del /q *"])
        assert not r.allowed

    def test_windows_caret_blocked(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("ls", ["^C"])
        assert not r.allowed

    def test_windows_percent_blocked(self, policy: PolicyEngine) -> None:
        r = policy.validate_shell("ls", ["%USERPROFILE%"])
        assert not r.allowed


# ── Tool classification ──────────────────────────────────────────


class TestClassifyTool:
    def test_safe_tool(self, policy: PolicyEngine) -> None:
        r = policy.classify_tool("list_files", "safe", False)
        assert r.allowed
        assert r.classification == "safe"

    def test_approval_required_tool(self, policy: PolicyEngine) -> None:
        r = policy.classify_tool("write_file", "medium", True)
        assert r.allowed
        assert r.classification == "approval_required"

    def test_high_risk_forces_approval(self, policy: PolicyEngine) -> None:
        r = policy.classify_tool("run_shell_safe", "high", False)
        assert r.allowed
        assert r.classification == "approval_required"
