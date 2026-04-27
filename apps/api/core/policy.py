"""
Policy engine — the hard security boundary.

Classifies every proposed action as safe, approval-required, or
forbidden. Validates paths stay inside the workspace and shell
commands are on the allowlist. All decisions are audit-logged.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..config import Settings
from ..platform_utils import IS_WINDOWS, get_shell_allowlist

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Injection-pattern regexes
# ------------------------------------------------------------------

# Characters / sequences that enable shell chaining or redirection
_UNIX_INJECTION_PATTERN = re.compile(r"[;|`]|\$\(|&&|\|\||>>|<<|[><]")
# Windows-specific metacharacters on top of the above
_WINDOWS_INJECTION_PATTERN = re.compile(r"[&^]|%[a-zA-Z_]+%|cmd\s*/[cCkK]")


class PolicyDecision(BaseModel):
    """Outcome of a policy check."""

    allowed: bool
    requires_approval: bool = False
    reason: str = ""
    risk_level: str = "safe"


class PolicyEngine:
    """
    Server-side policy enforcement.

    Every proposed action passes through here before execution.
    The engine never grants execution by itself — it only classifies.
    """

    # Directories that must never be accessed regardless of workspace
    BLOCKED_DIRS: list[str] = [
        ".ssh",
        ".gnupg",
        ".aws",
        ".config",
        ".kube",
        ".docker",
    ]

    # Tools that are always safe to auto-execute
    SAFE_TOOLS: set[str] = {
        "list_files",
        "read_file",
        "search_in_files",
        "remember_fact",
        "search_memory",
    }

    # Tools that always require user approval
    APPROVAL_TOOLS: set[str] = {
        "write_file",
        "run_shell_safe",
    }

    def __init__(self, workspace_root: str | Path, config: Settings | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.is_windows = IS_WINDOWS
        self.shell_allowlist = get_shell_allowlist()
        self.config = config
        logger.info(
            "PolicyEngine initialised — workspace=%s platform=%s",
            self.workspace_root,
            sys.platform,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_step(self, tool_name: str, args: dict[str, Any]) -> PolicyDecision:
        """
        Validate a planned step against all policy rules.

        Args:
            tool_name: Canonical tool name from the plan.
            args: Tool arguments from the plan.

        Returns:
            PolicyDecision indicating whether the step may proceed.
        """
        # 1. Check if the tool is known
        all_known = self.SAFE_TOOLS | self.APPROVAL_TOOLS
        if tool_name not in all_known:
            return PolicyDecision(
                allowed=False,
                reason=f"Unknown tool: {tool_name}",
                risk_level="high",
            )

        # 2. Tool-specific validation
        if tool_name in ("list_files", "read_file", "search_in_files"):
            path_arg = args.get("path", "")
            return self._validate_read_path(path_arg, tool_name)

        if tool_name == "write_file":
            path_arg = args.get("path", "")
            path_decision = self.validate_path(path_arg)
            if not path_decision.allowed:
                return path_decision
            return PolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="File write requires user approval",
                risk_level="medium",
            )

        if tool_name == "run_shell_safe":
            command = args.get("command", "")
            cmd_args = args.get("args", [])
            cwd = args.get("cwd", "")
            shell_decision = self.validate_shell(command, cmd_args)
            if not shell_decision.allowed:
                return shell_decision
            # Also validate cwd
            if cwd:
                cwd_decision = self.validate_path(cwd)
                if not cwd_decision.allowed:
                    return PolicyDecision(
                        allowed=False,
                        reason=f"Shell cwd not in workspace: {cwd_decision.reason}",
                        risk_level="high",
                    )
            return PolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="Shell command requires user approval",
                risk_level="medium",
            )

        # Memory tools are always safe
        if tool_name in ("remember_fact", "search_memory"):
            return PolicyDecision(
                allowed=True,
                requires_approval=False,
                reason="Memory operation — safe",
                risk_level="safe",
            )

        return PolicyDecision(
            allowed=False,
            reason=f"No policy rule for tool: {tool_name}",
            risk_level="high",
        )

    def validate_path(self, path_str: str) -> PolicyDecision:
        """
        Cross-platform path validation.

        1. Expand ~ via Path.expanduser()
        2. Resolve to absolute path (normalises separators and symlinks)
        3. Check it is within workspace_root
        4. Check it is NOT in a blocked directory
        5. Block ../ traversal in the raw input as extra defence
        """
        if not path_str:
            return PolicyDecision(
                allowed=False,
                reason="Empty path",
                risk_level="high",
            )

        # Quick pre-check on raw input for traversal attempts
        normalised_raw = path_str.replace("\\", "/")
        if "/../" in normalised_raw or normalised_raw.startswith("../"):
            return PolicyDecision(
                allowed=False,
                reason="Path traversal detected",
                risk_level="high",
            )

        try:
            target = Path(path_str).expanduser()
            # If relative, resolve against workspace
            if not target.is_absolute():
                target = (self.workspace_root / target).resolve()
            else:
                target = target.resolve()
        except (OSError, ValueError) as exc:
            return PolicyDecision(
                allowed=False,
                reason=f"Invalid path: {exc}",
                risk_level="high",
            )

        # Workspace containment check
        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            return PolicyDecision(
                allowed=False,
                reason=f"Path outside workspace: {target}",
                risk_level="high",
            )

        # Blocked directory check
        for part in target.parts:
            if part.lower() in (d.lower() for d in self.BLOCKED_DIRS):
                return PolicyDecision(
                    allowed=False,
                    reason=f"Access to blocked directory: {part}",
                    risk_level="high",
                )

        return PolicyDecision(
            allowed=True,
            reason="Path is within workspace",
            risk_level="safe",
        )

    def validate_shell(self, command: str, args: list[str]) -> PolicyDecision:
        """
        Validate a shell command against the allowlist and check each
        argument for injection patterns.

        Args:
            command: Canonical Unix command name (pwd, ls, find, cat, grep).
            args: List of arguments to pass to the command.

        Returns:
            PolicyDecision.
        """
        # 1. Command allowlist
        if command not in self.shell_allowlist:
            return PolicyDecision(
                allowed=False,
                reason=f"Command not in allowlist: {command}",
                risk_level="high",
            )

        # 2. Validate each argument
        for i, arg in enumerate(args):
            injection = self._check_injection(arg)
            if injection:
                return PolicyDecision(
                    allowed=False,
                    reason=f"Injection pattern in arg[{i}]: {injection}",
                    risk_level="high",
                )

        # 3. Validate path arguments against workspace boundary
        # Heuristic: any arg that looks like a path
        for arg in args:
            if not arg.startswith("-"):
                # Could be a path — validate it
                path_decision = self.validate_path(arg)
                if not path_decision.allowed:
                    return PolicyDecision(
                        allowed=False,
                        reason=f"Shell argument path not allowed: {path_decision.reason}",
                        risk_level="high",
                    )

        return PolicyDecision(
            allowed=True,
            requires_approval=True,
            reason="Allowed shell command",
            risk_level="medium",
        )

    def classify_risk(self, tool_name: str, args: dict[str, Any] | None = None) -> str:
        """Return risk_level string for a tool + args combination."""
        if tool_name in self.SAFE_TOOLS:
            return "safe"
        if tool_name == "write_file":
            mode = (args or {}).get("mode", "create")
            return "medium" if mode == "create" else "high"
        if tool_name == "run_shell_safe":
            return "medium"
        return "high"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_read_path(self, path_str: str, tool_name: str) -> PolicyDecision:
        """Validate a read-only path access."""
        decision = self.validate_path(path_str)
        if not decision.allowed:
            return decision
        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            reason=f"Read access via {tool_name}",
            risk_level="safe",
        )

    def _check_injection(self, arg: str) -> str | None:
        """
        Check a single argument for injection patterns.

        Returns a description of the matched pattern, or None if clean.
        """
        # Universal checks
        match = _UNIX_INJECTION_PATTERN.search(arg)
        if match:
            return f"unix metacharacter: {match.group()}"

        # Windows-specific checks
        if self.is_windows:
            match = _WINDOWS_INJECTION_PATTERN.search(arg)
            if match:
                return f"windows metacharacter: {match.group()}"

        return None
