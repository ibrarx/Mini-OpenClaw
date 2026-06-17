"""skills/system_info — Report CPU, memory, disk, platform details, and uptime."""
from __future__ import annotations
import asyncio
import os
import platform
import time
from typing import Any

import psutil

from apps.api.models.run import RiskLevel, ToolResult
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext

# Concrete sections (the enum also accepts "all" as a convenience alias).
_SECTIONS = ("cpu", "memory", "disk", "platform")
_GB = 1024 ** 3


class SystemInfoTool(BaseTool):
    """Stateless, safe, read-only host telemetry. No filesystem writes, no network."""

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="system_info",
            description=(
                "Get current system information: CPU usage, memory usage, disk usage, "
                "platform details, and uptime."
            ),
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            input_schema={
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["cpu", "memory", "disk", "platform", "all"],
                        },
                        "description": "Which info sections to return. Defaults to ['all'].",
                        "default": ["all"],
                    },
                },
                "required": [],
            },
            output_schema={"type": "object"},
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        started = self._now()
        requested = args.get("sections")
        if requested is None:
            requested = ["all"]
        if not isinstance(requested, list):
            return self._error(args, "sections must be an array of strings.", started)

        if "all" in requested:
            wanted = list(_SECTIONS) + ["uptime"]
        else:
            wanted = [s for s in requested if s in _SECTIONS]
            if not wanted:
                return self._error(args, f"No valid sections in {requested!r}.", started)

        try:
            # psutil calls (notably cpu_percent with an interval) block; keep the
            # event loop free by running collection in a worker thread.
            output = await asyncio.to_thread(self._collect, wanted)
        except (psutil.Error, OSError) as exc:
            return self._error(args, f"Could not read system info: {exc}", started)

        return self._success(args, output, started)

    def _collect(self, wanted: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        if "cpu" in wanted:
            try:
                freq = psutil.cpu_freq()
            except (NotImplementedError, AttributeError):
                freq = None  # not exposed in some VMs/containers
            out["cpu"] = {
                "usage_percent": psutil.cpu_percent(interval=0.5),
                "core_count": psutil.cpu_count(logical=True),
                "frequency_mhz": round(freq.current, 1) if freq else None,
            }

        if "memory" in wanted:
            vm = psutil.virtual_memory()
            out["memory"] = {
                "total_gb": round(vm.total / _GB, 1),
                "used_gb": round(vm.used / _GB, 1),
                "percent": vm.percent,
            }

        if "disk" in wanted:
            # Cross-platform root: "/" on POSIX, "C:\\" (current drive) on Windows.
            root = os.path.abspath(os.sep)
            du = psutil.disk_usage(root)
            out["disk"] = {
                "total_gb": round(du.total / _GB, 1),
                "used_gb": round(du.used / _GB, 1),
                "free_gb": round(du.free / _GB, 1),
                "percent": du.percent,
            }

        if "platform" in wanted:
            out["platform"] = {
                "system": platform.system(),
                "node": platform.node(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            }

        if "uptime" in wanted:
            boot = psutil.boot_time()
            out["uptime"] = {
                "boot_time": boot,
                "uptime_seconds": round(time.time() - boot, 1),
            }

        return out
