"""skills/run_shell_safe — Execute allowlisted commands inside the workspace."""
from __future__ import annotations
import asyncio, logging, subprocess
from pathlib import Path
from typing import Any
from apps.api.models.run import ErrorKind, RetryPolicy, RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.platform_utils import IS_WINDOWS, get_shell_allowlist
from apps.api.skills.base import BaseTool, ToolContext, resolve_tool_path

logger = logging.getLogger(__name__)

class RunShellSafeTool(BaseTool):
    def manifest(self) -> ToolManifest:
        return ToolManifest(name="run_shell_safe",
                            description="Execute a limited allowlisted command (pwd, ls, find, cat, grep) inside the workspace.",
                            risk_level=RiskLevel.MEDIUM, approval_required=True,
                            input_schema={"type":"object","properties":{
                            "command":{"type":"string","enum":["pwd","ls","find","cat","grep"]},
                            "args":{"type":"array","items":{"type":"string"}},
                            "cwd":{"type":"string"}},"required":["command","args","cwd"]})

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_retries=1, idempotent=True)

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        command = args["command"]
        cmd_args: list[str] = args.get("args", [])
        cwd_arg = args.get("cwd", ".")
        try:
            _root, cwd = resolve_tool_path(cwd_arg, context)
        except ValueError as exc:
            return self._error(args, f"Working directory error: {exc}", started,
                               error_kind=ErrorKind.PERMANENT)
        if not cwd.is_dir():
            return self._error(args, f"Working directory not found: {cwd_arg}", started,
                               error_kind=ErrorKind.PERMANENT)
        allowlist = get_shell_allowlist()
        if command not in allowlist:
            return self._error(args, f"Command not allowed: {command}", started,
                               error_kind=ErrorKind.PERMANENT)
        native_cmd = allowlist[command]
        try:
            if IS_WINDOWS:
                full_cmd = f"{native_cmd} {' '.join(cmd_args)}" if cmd_args else native_cmd
                proc = await asyncio.create_subprocess_shell(full_cmd, cwd=str(cwd),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                proc = await asyncio.create_subprocess_exec(native_cmd, *cmd_args, cwd=str(cwd),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()
            if proc.returncode != 0:
                return self._error(args, f"Command failed (exit {proc.returncode}): {err or out}", started,
                                   error_kind=ErrorKind.PERMANENT)
            return self._success(args, {"command": command, "native_command": native_cmd,
                                         "stdout": out[:5000], "stderr": err[:1000] if err else None,
                                         "exit_code": proc.returncode}, started)
        except asyncio.TimeoutError:
            return self._error(args, "Command timed out after 15s", started,
                               error_kind=ErrorKind.TRANSIENT)
        except FileNotFoundError:
            return self._error(args, f"Command not found: {native_cmd}", started,
                               error_kind=ErrorKind.PERMANENT)
        except Exception as exc:
            return self._error(args, f"Execution error: {exc}", started,
                               error_kind=ErrorKind.TRANSIENT)
