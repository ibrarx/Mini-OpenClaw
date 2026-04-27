"""
Policy engine — the hard security boundary.

Classifies every proposed action as safe, approval-required, or
forbidden. Enforces workspace path boundaries, shell allowlists,
and injection-pattern blocking. Server-side enforcement only.
"""
from __future__ import annotations
import logging, re, sys
from pathlib import Path
from typing import Any
from ..models.step import PolicyDecision, RiskLevel, RunStep
from ..platform_utils import IS_WINDOWS, get_shell_allowlist

logger = logging.getLogger(__name__)

_UNIX_DANGEROUS = re.compile(r"[;|`]|\$\(|&&|\|\||>>|<<|[><]")
_WIN_DANGEROUS = re.compile(r"[&^]|%[a-zA-Z_]+%|cmd\s*/[cCkK]")
_ALLOWED_COMMANDS = frozenset({"pwd", "ls", "find", "cat", "grep"})
BLOCKED_DIRS = [".ssh", ".gnupg", ".aws", ".config", ".kube", ".docker"]


class PolicyEngine:
    """Validates proposed tool invocations against security policy."""

    def __init__(self, workspace_root: str | Path) -> None:
        self._workspace = Path(workspace_root).resolve()

    @property
    def workspace_root(self) -> Path:
        return self._workspace

    def validate_step(self, step: RunStep) -> PolicyDecision:
        """Evaluate a proposed run step and return a policy decision."""
        tool = step.tool
        if tool == "run_shell_safe":
            return self.validate_shell(step.args.get("command",""), step.args.get("args",[]))
        if tool == "write_file":
            path = step.args.get("path","")
            pd = self.validate_path(path, write=True)
            if not pd.allowed:
                return pd
            return PolicyDecision(allowed=True, classification="approval_required", reason="File write requires user approval")
        if tool in ("read_file", "list_files", "search_in_files"):
            return self.validate_path(step.args.get("path",""), write=False)
        if tool in ("remember_fact", "search_memory"):
            return PolicyDecision(allowed=True, classification="safe")
        return PolicyDecision(allowed=False, classification="forbidden", reason=f"Unknown tool: {tool}")

    def validate_path(self, path: str, write: bool = False) -> PolicyDecision:
        """Check that a path stays within the workspace boundary."""
        if not path:
            return PolicyDecision(allowed=False, classification="forbidden", reason="Empty path")
        normalised = path.replace("\\", "/")
        if "/../" in normalised or normalised.startswith("../"):
            return PolicyDecision(allowed=False, classification="forbidden", reason="Path traversal detected")
        try:
            target = Path(path).expanduser()
            if not target.is_absolute():
                target = (self._workspace / target).resolve()
            else:
                target = target.resolve()
        except (ValueError, OSError) as exc:
            return PolicyDecision(allowed=False, classification="forbidden", reason=f"Invalid path: {exc}")
        try:
            target.relative_to(self._workspace)
        except ValueError:
            return PolicyDecision(allowed=False, classification="forbidden", reason=f"Path outside workspace: {target}")
        for part in target.parts:
            if part.lower() in (d.lower() for d in BLOCKED_DIRS):
                return PolicyDecision(allowed=False, classification="forbidden", reason=f"Access to blocked directory: {part}")
        if write:
            return PolicyDecision(allowed=True, classification="approval_required", reason="File write requires user approval")
        return PolicyDecision(allowed=True, classification="safe")

    def validate_shell(self, command: str, args: list[str]) -> PolicyDecision:
        """Validate an allowlisted shell command."""
        if command not in _ALLOWED_COMMANDS:
            return PolicyDecision(allowed=False, classification="forbidden", reason=f"Command not in allowlist: {command}")
        # Always check Unix metacharacters (;  |  `  $()  &&  ||  > < etc.)
        # On Windows, additionally check Windows-specific patterns (& ^ %var%)
        for arg in args:
            if _UNIX_DANGEROUS.search(arg):
                return PolicyDecision(allowed=False, classification="forbidden", reason=f"Dangerous metacharacter in argument: {arg!r}")
            if IS_WINDOWS and _WIN_DANGEROUS.search(arg):
                return PolicyDecision(allowed=False, classification="forbidden", reason=f"Dangerous metacharacter in argument: {arg!r}")
        # Validate path args against workspace
        for arg in args:
            if not arg.startswith("-"):
                pd = self.validate_path(arg, write=False)
                if not pd.allowed:
                    return PolicyDecision(allowed=False, classification="forbidden", reason=f"Shell arg path: {pd.reason}")
        return PolicyDecision(allowed=True, classification="approval_required", reason="Shell command requires user approval")

    def classify_risk(self, tool_name: str, args: dict | None = None) -> str:
        if tool_name in ("list_files","read_file","search_in_files","remember_fact","search_memory"):
            return "safe"
        if tool_name == "write_file":
            mode = (args or {}).get("mode","create")
            return "medium" if mode == "create" else "high"
        if tool_name == "run_shell_safe":
            return "medium"
        return "high"
