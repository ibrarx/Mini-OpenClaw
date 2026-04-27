"""run_shell_safe tool — execute an allowlisted command inside the workspace.
CRITICAL SECURITY TOOL. Cross-platform."""
from __future__ import annotations
import asyncio, logging, re, subprocess
from pathlib import Path
from typing import Any
from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from ..platform_utils import IS_WINDOWS, get_shell_allowlist
from .base import BaseTool, _now_iso

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 30; MAX_OUTPUT = 64 * 1024
_UNIX_INJ = re.compile(r"[;|`]|\$\(|&&|\|\||>>|<<|[><]")
_WIN_INJ = re.compile(r"[&^]|%[a-zA-Z_]+%|cmd\s*/[cCkK]")

class RunShellSafeTool(BaseTool):
    """Execute a limited allowlisted shell command inside the workspace."""
    _allowlist = get_shell_allowlist()

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="run_shell_safe",
            description="Execute a limited allowlisted command inside the workspace.",
            risk_level=RiskLevel.HIGH, approval_required=True, read_scope="workspace",
            input_schema={"type":"object","properties":{"command":{"type":"string","enum":["pwd","ls","find","cat","grep"]},"args":{"type":"array","items":{"type":"string"}},"cwd":{"type":"string"}},"required":["command","args","cwd"],"additionalProperties":False},
            output_schema={"type":"object","properties":{"stdout":{"type":"string"},"stderr":{"type":"string"},"exit_code":{"type":"integer"}}},
            failure_modes=["command_not_allowed","dangerous_args","timeout"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        started_at = _now_iso()
        command = args.get("command",""); cmd_args: list[str] = args.get("args",[]); cwd_str = args.get("cwd","")
        workspace = Path(context["workspace_root"]).resolve()
        if command not in self._allowlist:
            return self._error(args, f"Command not in allowlist: {command}", started_at)
        for i, arg in enumerate(cmd_args):
            issue = _check_injection(arg)
            if issue:
                return self._error(args, f"Injection pattern in arg[{i}]: {issue}", started_at)
        cwd_path = (workspace / cwd_str).resolve() if cwd_str else workspace
        if cwd_str:
            cp = Path(cwd_str)
            cwd_path = (workspace / cp).resolve() if not cp.is_absolute() else cp.resolve()
        try:
            cwd_path.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Working directory outside workspace: {cwd_path}", started_at)
        if not cwd_path.exists():
            return self._error(args, f"Working directory not found: {cwd_path}", started_at)
        for arg in cmd_args:
            if not arg.startswith("-"):
                ap = Path(arg)
                resolved = ap.resolve() if ap.is_absolute() else (cwd_path / ap).resolve()
                try:
                    resolved.relative_to(workspace)
                except ValueError:
                    return self._error(args, f"Path argument outside workspace: {arg}", started_at)
        native_cmd = self._allowlist[command]
        try:
            cmd_line = [native_cmd] + cmd_args
            result = await asyncio.to_thread(
                subprocess.run, cmd_line, capture_output=True, timeout=TIMEOUT_SECONDS,
                cwd=str(cwd_path), shell=IS_WINDOWS, text=True,
            )
            return self._success(args, {"stdout": (result.stdout or "")[:MAX_OUTPUT], "stderr": (result.stderr or "")[:MAX_OUTPUT], "returncode": result.returncode}, started_at)
        except subprocess.TimeoutExpired:
            return self._error(args, f"Command timed out after {TIMEOUT_SECONDS}s", started_at)
        except FileNotFoundError:
            return self._error(args, f"Command not found: {native_cmd}", started_at)
        except OSError as exc:
            return self._error(args, f"Execution error: {exc}", started_at)

def _check_injection(arg: str) -> str | None:
    m = _UNIX_INJ.search(arg)
    if m: return f"unix metacharacter: {m.group()}"
    if IS_WINDOWS:
        m = _WIN_INJ.search(arg)
        if m: return f"windows metacharacter: {m.group()}"
    return None
