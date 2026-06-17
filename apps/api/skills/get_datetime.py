"""skills/get_datetime — Return the current date and time, optionally in a given timezone."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.api.models.run import RiskLevel, ToolResult
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext

_DEFAULT_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


class GetDatetimeTool(BaseTool):
    """Stateless, safe clock tool. No filesystem or network access."""

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="get_datetime",
            description="Get the current date and time, optionally in a specific timezone.",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            input_schema={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone name (e.g. 'Europe/Vienna', 'US/Eastern'). Defaults to UTC.",
                        "default": "UTC",
                    },
                    "format": {
                        "type": "string",
                        "description": "strftime format string. Defaults to ISO 8601.",
                        "default": _DEFAULT_FORMAT,
                    },
                },
                "required": [],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "datetime": {"type": "string"},
                    "timezone": {"type": "string"},
                    "utc_offset": {"type": "string"},
                    "unix_timestamp": {"type": "number"},
                },
                "required": ["datetime", "timezone", "utc_offset", "unix_timestamp"],
            },
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        started = self._now()
        tz_name = args.get("timezone") or "UTC"
        fmt = args.get("format") or _DEFAULT_FORMAT

        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            # ZoneInfoNotFoundError subclasses KeyError; also covers a missing
            # IANA database (e.g. a bare Windows install without the `tzdata`
            # package), in which case every lookup fails here.
            return self._error(args, f"Unknown or unavailable timezone {tz_name!r}: {exc}", started)

        now = datetime.now(tz)

        offset = now.utcoffset()
        if offset is None:
            offset_str = "+00:00"
        else:
            total = int(offset.total_seconds())
            sign = "+" if total >= 0 else "-"
            total = abs(total)
            offset_str = f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"

        try:
            formatted = now.strftime(fmt)
        except (ValueError, TypeError) as exc:
            return self._error(args, f"Invalid format string {fmt!r}: {exc}", started)

        return self._success(
            args,
            {
                "datetime": formatted,
                "timezone": tz_name,
                "utc_offset": offset_str,
                "unix_timestamp": now.timestamp(),
            },
            started,
        )
