"""
run_shell_safe — Execute a limited allowlisted command inside the workspace.

Risk level: Medium to High
Approval required: Yes

CRITICAL SECURITY TOOL — this is the most sensitive tool in the system.
It translates canonical Unix command names to native OS equivalents
and executes via subprocess with strict argument validation.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..models.tool_manifest import (
    ExecutionContext,
    RiskLevel,
    ToolManifest,
    ToolResult,
)
from ..platform_utils import IS_WINDOWS, get_shell_allowlist
from .base import BaseTool, _now_iso

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB output cap

# Characters that enable shell chaining or injection
_UNIX_INJECTION = re.compile(r"[;|`]|\$\(|&&|\|\||>>|<<|[><]")
_WINDOWS_INJECTION = re.compile(r"[&^]|%[a-zA-Z_]+%|cmd\s*/[cCkK]")


class RunShellSafeTool(BaseTool):
    """Execute a limited allowlisted shell command inside the workspace."""

    def __init__(self) -> None:
        self._allowlist = get_shell_allowlist()

    def get_manifest(self) -> ToolManifest:
        return ToolManifest(
            name="run_shell_safe",
            description=(
                "Execute a limited allowlisted command inside the workspace. "
                "Allowed commands: pwd, ls, find, cat, grep."
            ),
            risk_level=RiskLevel.MEDIUM,
            approval_required=True,
            read_scope="workspace",
            write_scope="",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": ["pwd", "ls", "find", "cat", "grep"],
                    },
                    "args": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                },
                "required": ["command", "args", "cwd"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "stdout": {"type": "string"},
                    "stderr": {"type": "string"},
                    "returncode": {"type": "integer"},
                },
            },
            failure_modes=[
                "command_not_allowed",
                "injection_detected",
                "path_outside_workspace",
                "timeout",
                "execution_error",
            ],
        )

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        started_at = _now_iso()

        command = args.get("command", "")
        cmd_args: list[str] = args.get("args", [])
        cwd_str = args.get("cwd", "")

        workspace = Path(context.workspace_root).resolve()

        # 1. Validate command is in allowlist
        if command not in self._allowlist:
            return self._error(
                args,
                f"Command not in allowlist: {command}",
                started_at,
            )

        # 2. Validate each argument for injection patterns
        for i, arg in enumerate(cmd_args):
            issue = self._check_injection(arg)
            if issue:
                return self._error(
                    args,
                    f"Injection pattern in arg[{i}]: {issue}",
                    started_at,
                )

        # 3. Validate and resolve cwd
        if cwd_str:
            cwd_path = Path(cwd_str)
            if not cwd_path.is_absolute():
                cwd_path = (workspace / cwd_path).resolve()
            else:
                cwd_path = cwd_path.resolve()
        else:
            cwd_path = workspace

        try:
            cwd_path.relative_to(workspace)
        except ValueError:
            return self._error(
                args,
                f"Working directory outside workspace: {cwd_path}",
                started_at,
            )

        if not cwd_path.exists():
            return self._error(args, f"Working directory not found: {cwd_path}", started_at)

        # 4. Validate path arguments against workspace
        for arg in cmd_args:
            if not arg.startswith("-"):
                arg_path = Path(arg)
                if arg_path.is_absolute():
                    try:
                        arg_path.resolve().relative_to(workspace)
                    except ValueError:
                        return self._error(
                            args,
                            f"Path argument outside workspace: {arg}",
                            started_at,
                        )
                else:
                    resolved = (cwd_path / arg_path).resolve()
                    try:
                        resolved.relative_to(workspace)
                    except ValueError:
                        return self._error(
                            args,
                            f"Path argument resolves outside workspace: {arg}",
                            started_at,
                        )

        # 5. Translate command to native equivalent
        native_command = self._allowlist[command]

        # 6. Build and execute the command
        try:
            if IS_WINDOWS:
                # Windows builtins (dir, type, cd) require shell=True.
                # We still validate strictly above, so this is safe.
                cmd_line = [native_command] + cmd_args
                result = await asyncio.to_thread(
                    subprocess.run,
                    cmd_line,
                    capture_output=True,
                    timeout=TIMEOUT_SECONDS,
                    cwd=str(cwd_path),
                    shell=True,
                    text=True,
                )
            else:
                # Unix: NEVER shell=True. Pass as list.
                cmd_line = [native_command] + cmd_args
                result = await asyncio.to_thread(
                    subprocess.run,
                    cmd_line,
                    capture_output=True,
                    timeout=TIMEOUT_SECONDS,
                    cwd=str(cwd_path),
                    shell=False,
                    text=True,
                )

            stdout = (result.stdout or "")[:MAX_OUTPUT_BYTES]
            stderr = (result.stderr or "")[:MAX_OUTPUT_BYTES]

            return self._success(
                args,
                {
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": result.returncode,
                },
                started_at,
            )

        except subprocess.TimeoutExpired:
            return self._error(args, f"Command timed out after {TIMEOUT_SECONDS}s", started_at)
        except FileNotFoundError:
            return self._error(
                args,
                f"Command not found on this platform: {native_command}",
                started_at,
            )
        except OSError as exc:
            return self._error(args, f"Execution error: {exc}", started_at)

    @staticmethod
    def _check_injection(arg: str) -> str | None:
        """Check a single argument for injection patterns."""
        match = _UNIX_INJECTION.search(arg)
        if match:
            return f"unix metacharacter: {match.group()}"

        if IS_WINDOWS:
            match = _WINDOWS_INJECTION.search(arg)
            if match:
                return f"windows metacharacter: {match.group()}"

        return None
