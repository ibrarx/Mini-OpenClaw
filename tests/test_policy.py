"""Tests for the policy engine."""
from pathlib import Path
import pytest
from apps.api.core.policy import PolicyEngine
from apps.api.models.step import RunStep

@pytest.fixture
def policy(tmp_workspace: Path) -> PolicyEngine:
    return PolicyEngine(workspace_root=str(tmp_workspace))

class TestValidatePath:
    def test_inside_workspace_allowed(self, policy, tmp_workspace):
        f = tmp_workspace / "readme.md"; f.touch()
        assert policy.validate_path(str(f)).allowed

    def test_relative_allowed(self, policy):
        assert policy.validate_path("subdir/file.txt").allowed

    def test_outside_denied(self, policy):
        r = policy.validate_path("/etc/passwd")
        assert not r.allowed

    def test_traversal_denied(self, policy):
        r = policy.validate_path("../../../etc/passwd")
        assert not r.allowed

    def test_ssh_blocked(self, policy, tmp_workspace):
        (tmp_workspace / ".ssh").mkdir()
        assert not policy.validate_path(str(tmp_workspace / ".ssh" / "id_rsa")).allowed

    def test_aws_blocked(self, policy, tmp_workspace):
        (tmp_workspace / ".aws").mkdir()
        assert not policy.validate_path(str(tmp_workspace / ".aws" / "credentials")).allowed

    def test_empty_denied(self, policy):
        assert not policy.validate_path("").allowed

    def test_home_expansion(self, policy):
        assert not policy.validate_path("~/secret.txt").allowed

    def test_backslash_path(self, policy):
        assert policy.validate_path("subdir\\file.txt").allowed

class TestValidateShell:
    def test_ls_allowed(self, policy, tmp_workspace):
        assert policy.validate_shell("ls", [str(tmp_workspace)]).allowed

    def test_pwd_allowed(self, policy):
        assert policy.validate_shell("pwd", []).allowed

    def test_rm_denied(self, policy):
        r = policy.validate_shell("rm", ["-rf","/"])
        assert not r.allowed

    def test_semicolon(self, policy):
        assert not policy.validate_shell("ls", ["; rm -rf /"]).allowed

    def test_pipe(self, policy):
        assert not policy.validate_shell("ls", ["| cat /etc/passwd"]).allowed

    def test_ampersand(self, policy):
        assert not policy.validate_shell("ls", ["&& rm -rf /"]).allowed

    def test_backtick(self, policy):
        assert not policy.validate_shell("ls", ["`whoami`"]).allowed

    def test_dollar_paren(self, policy):
        assert not policy.validate_shell("ls", ["$(cat /etc/passwd)"]).allowed

    def test_redirect(self, policy):
        assert not policy.validate_shell("ls", ["> /tmp/out"]).allowed

    def test_path_outside(self, policy):
        assert not policy.validate_shell("cat", ["/etc/passwd"]).allowed

class TestValidateStep:
    def test_safe_tool(self, policy, tmp_workspace):
        step = RunStep(step_id="s1", tool="list_files", args={"path": str(tmp_workspace)})
        d = policy.validate_step(step)
        assert d.allowed and d.classification == "safe"

    def test_write_approval(self, policy):
        step = RunStep(step_id="s1", tool="write_file", args={"path":"test.txt","content":"hi","mode":"create"})
        d = policy.validate_step(step)
        assert d.allowed and d.classification == "approval_required"

    def test_shell_approval(self, policy):
        step = RunStep(step_id="s1", tool="run_shell_safe", args={"command":"pwd","args":[],"cwd":""})
        d = policy.validate_step(step)
        assert d.allowed and d.classification == "approval_required"

    def test_unknown_denied(self, policy):
        step = RunStep(step_id="s1", tool="hack", args={})
        assert not policy.validate_step(step).allowed

    def test_memory_safe(self, policy):
        for t in ("remember_fact", "search_memory"):
            step = RunStep(step_id="s1", tool=t, args={})
            d = policy.validate_step(step)
            assert d.allowed and d.classification == "safe"

    def test_write_outside_denied(self, policy):
        step = RunStep(step_id="s1", tool="write_file", args={"path":"/etc/evil","content":"x","mode":"create"})
        assert not policy.validate_step(step).allowed

class TestClassifyRisk:
    def test_safe(self, policy):
        assert policy.classify_risk("list_files") == "safe"
    def test_medium(self, policy):
        assert policy.classify_risk("write_file", {"mode":"create"}) == "medium"
    def test_high(self, policy):
        assert policy.classify_risk("write_file", {"mode":"overwrite"}) == "high"
