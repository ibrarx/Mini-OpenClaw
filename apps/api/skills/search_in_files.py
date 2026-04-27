"""
search_in_files — Recursive grep-like search inside the workspace.

Risk level: Safe
Approval required: No
"""

from __future__ import annotations

import fnmatch
import logging
import re
from pathlib import Path
from typing import Any

from ..models.tool_manifest import (
    ExecutionContext,
    RiskLevel,
    ToolManifest,
    ToolResult,
)
from .base import BaseTool, _now_iso

logger = logging.getLogger(__name__)

MAX_MATCHES = 200  # Cap total matches returned


class SearchInFilesTool(BaseTool):
    """Search for keywords or patterns across text files in the workspace."""

    def get_manifest(self) -> ToolManifest:
        return ToolManifest(
            name="search_in_files",
            description="Search for keywords or patterns across text files in the workspace.",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            read_scope="workspace",
            write_scope="",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "query": {"type": "string"},
                    "file_glob": {"type": "string"},
                },
                "required": ["path", "query"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "matches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file": {"type": "string"},
                                "line_number": {"type": "integer"},
                                "line": {"type": "string"},
                            },
                        },
                    },
                    "total_matches": {"type": "integer"},
                    "truncated": {"type": "boolean"},
                },
            },
            failure_modes=["path_not_found", "permission_denied", "invalid_pattern"],
        )

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        started_at = _now_iso()

        path_str = args.get("path", ".")
        query = args.get("query", "")
        file_glob = args.get("file_glob", "*")

        if not query:
            return self._error(args, "Empty search query", started_at)

        workspace = Path(context.workspace_root).resolve()
        target = Path(path_str)
        if not target.is_absolute():
            target = (workspace / target).resolve()
        else:
            target = target.resolve()

        # Containment check
        try:
            target.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Path outside workspace: {target}", started_at)

        if not target.exists():
            return self._error(args, f"Path not found: {target}", started_at)

        # Compile pattern (case-insensitive plain text search)
        try:
            pattern = re.compile(re.escape(query), re.IGNORECASE)
        except re.error as exc:
            return self._error(args, f"Invalid pattern: {exc}", started_at)

        matches: list[dict[str, Any]] = []
        total = 0

        files_to_search: list[Path] = []
        if target.is_file():
            files_to_search = [target]
        else:
            files_to_search = sorted(target.rglob("*"))

        for file_path in files_to_search:
            if not file_path.is_file():
                continue
            if not fnmatch.fnmatch(file_path.name, file_glob):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                continue

            for line_num, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    total += 1
                    if len(matches) < MAX_MATCHES:
                        matches.append({
                            "file": str(file_path.relative_to(workspace)),
                            "line_number": line_num,
                            "line": line.rstrip(),
                        })

        return self._success(
            args,
            {
                "matches": matches,
                "total_matches": total,
                "truncated": total > MAX_MATCHES,
            },
            started_at,
        )
