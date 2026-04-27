"""
Policy engine — the hard security boundary.

Classifies every proposed action as safe, approval-required, or
forbidden. Enforces workspace path boundaries, shell allowlists,
and injection-pattern blocking. Server-side enforcement only.

Full implementation in T03; this file provides the class interface
and basic path / shell validation logic.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..models.step import PolicyDecision, RiskLevel, RunStep

logger = logging.getLogger(__name__)

# Shell metacharacters that must never appear in arguments
_UNIX_DANGEROUS = re.compile(r"[;&|`$()><]")
_WIN_DANGEROUS = re.compile(r'[;&|`$()<>^%"]')

_ALLOWED_COMMANDS = frozenset({"pwd", "ls", "find", "cat", "grep"})


class PolicyEngine:
    """Validates proposed tool invocations against security policy.

    Args:
        workspace_root: Absolute path to the allowed workspace directory.
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self._workspace = Path(workspace_root).resolve()

    # --- public API ---

    def validate_step(self, step: RunStep) -> PolicyDecision:
        """Evaluate a proposed run step and return a policy decision.

        Args:
            step: The planned tool invocation to validate.

        Returns:
            A PolicyDecision indicating whether execution is allowed.
        """
        tool = step.tool

        # Forbidden tools (not in V1 registry) — will be checked
        # against the real registry in T03.
        if tool == "run_shell_safe":
            return self.validate_shell(
                step.args.get("command", ""),
                step.args.get("args", []),
            )
        if tool == "write_file":
            path = step.args.get("path", "")
            return self.validate_path(path, write=True)
        if tool in ("read_file", "list_files", "search_in_files"):
            path = step.args.get("path", "")
            return self.validate_path(path, write=False)
        if tool in ("remember_fact", "search_memory"):
            return PolicyDecision(allowed=True, classification="safe")

        return PolicyDecision(
            allowed=False,
            classification="forbidden",
            reason=f"Unknown tool: {tool}",
        )

    def validate_path(self, path: str, write: bool = False) -> PolicyDecision:
        """Check that a path stays within the workspace boundary.

        Args:
            path: The file path to validate.
            write: Whether the operation will modify files.

        Returns:
            PolicyDecision with classification.
        """
        try:
            resolved = (self._workspace / path).resolve()
        except (ValueError, OSError) as exc:
            return PolicyDecision(
                allowed=False,
                classification="forbidden",
                reason=f"Invalid path: {exc}",
            )

        if not str(resolved).startswith(str(self._workspace)):
            return PolicyDecision(
                allowed=False,
                classification="forbidden",
                reason="Path escapes workspace boundary",
            )

        if write:
            return PolicyDecision(
                allowed=True,
                classification="approval_required",
                reason="File write requires user approval",
            )
        return PolicyDecision(allowed=True, classification="safe")

    def validate_shell(
        self, command: str, args: list[str]
    ) -> PolicyDecision:
        """Validate an allowlisted shell command.

        Args:
            command: Canonical command name (pwd, ls, find, cat, grep).
            args: Command arguments as a list of strings.

        Returns:
            PolicyDecision indicating whether the command is permitted.
        """
        if command not in _ALLOWED_COMMANDS:
            return PolicyDecision(
                allowed=False,
                classification="forbidden",
                reason=f"Command not in allowlist: {command}",
            )

        # Check every argument for dangerous metacharacters
        pattern = _WIN_DANGEROUS if _is_windows() else _UNIX_DANGEROUS
        for arg in args:
            if pattern.search(arg):
                return PolicyDecision(
                    allowed=False,
                    classification="forbidden",
                    reason=f"Dangerous metacharacter in argument: {arg!r}",
                )

        return PolicyDecision(
            allowed=True,
            classification="approval_required",
            reason="Shell command requires user approval",
        )


def _is_windows() -> bool:
    import sys
    return sys.platform == "win32"
