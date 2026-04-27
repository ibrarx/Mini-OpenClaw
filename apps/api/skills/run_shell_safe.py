"""skills/run_shell_safe — Execute allowlisted commands inside the workspace."""
from __future__ import annotations
import asyncio, logging, subprocess
from pathlib import Path
from typing import Any
from apps.api.models.run import RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.platform_utils import IS_WINDOWS, get_shell_allowlist
from apps.api.skills.base import BaseTool, ToolContext

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

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        workspace = Path(context.workspace_root).resolve()
        command = args["command"]
        cmd_args: list[str] = args.get("args", [])
        cwd = (workspace / args.get("cwd", ".")).resolve()
        try:
            cwd.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Working directory outside workspace: {cwd}", started)
        if not cwd.is_dir():
            return self._error(args, f"Working directory not found: {args.get('cwd','.')}", started)
        allowlist = get_shell_allowlist()
        if command not in allowlist:
            return self._error(args, f"Command not allowed: {command}", started)
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
                return self._error(args, f"Command failed (exit {proc.returncode}): {err or out}", started)
            return self._success(args, {"command": command, "native_command": native_cmd,
                                         "stdout": out[:5000], "stderr": err[:1000] if err else None,
                                         "exit_code": proc.returncode}, started)
        except asyncio.TimeoutError:
            return self._error(args, "Command timed out after 15s", started)
        except FileNotFoundError:
            return self._error(args, f"Command not found: {native_cmd}", started)
        except Exception as exc:
            return self._error(args, f"Execution error: {exc}", started)
