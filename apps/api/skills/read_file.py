"""skills/read_file — Read one or more text files inside the workspace.

Supports two modes:
  - Single file: ``{"path": "foo.py"}`` → returns content, total_lines, truncated
  - Batch: ``{"paths": ["a.py", "b.py"]}`` → returns files dict with per-file content

Both modes enforce a character budget (``max_chars``) to prevent unbounded
output from flowing into RAM, the database, and eventually the LLM context.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.api.models.run import ErrorKind, RetryPolicy, RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext

# Module-level defaults used when no settings are injected (backward compat)
DEFAULT_MAX_BATCH = 10
DEFAULT_MAX_CHARS = 50_000


class ReadFileTool(BaseTool):
    def __init__(
        self,
        max_batch: int = DEFAULT_MAX_BATCH,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self._max_batch = max_batch
        self._max_chars = max_chars

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="read_file",
            description=(
                "Read text files inside the workspace. "
                "For ONE file: use 'path' (string). "
                "For MULTIPLE files: use 'paths' (array) — ALWAYS prefer this over separate calls. "
                "Never call read_file multiple times when a single batch call with 'paths' would work."
            ),
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Single file path (optional if paths provided)"},
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": self._max_batch,
                        "description": "Array of file paths for batch reading (preferred over path)",
                    },
                    "offset": {"type": "integer", "minimum": 0, "description": "Line offset (single-file mode only)"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5000,
                        "description": "Max lines per file. Defaults: 500 single, 200 batch.",
                    },
                },
                "additionalProperties": False,
            },
        )

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_retries=1, idempotent=True)

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        workspace = Path(context.workspace_root).resolve()

        paths = args.get("paths")
        path = args.get("path")

        if paths is not None:
            # Batch mode — paths takes priority
            if len(paths) > self._max_batch:
                return self._error(
                    args,
                    f"Too many files: {len(paths)} exceeds max_batch={self._max_batch}",
                    started,
                    error_kind=ErrorKind.PERMANENT,
                )
            return await self._read_batch(paths, args, context, workspace, started)
        elif path is not None:
            # Single-file mode
            return await self._read_single(path, args, context, workspace, started)
        else:
            return self._error(
                args,
                "Either 'path' (string) or 'paths' (array) must be provided",
                started,
                error_kind=ErrorKind.PERMANENT,
            )

    # ------------------------------------------------------------------
    # Single-file mode (backward-compatible output shape)
    # ------------------------------------------------------------------

    async def _read_single(
        self,
        file_path: str,
        args: dict[str, Any],
        context: ToolContext,
        workspace: Path,
        started: str,
    ) -> Any:
        target = (workspace / file_path).resolve()

        err = self._validate_target(target, file_path, workspace)
        if err is not None:
            return self._error(args, err, started, error_kind=ErrorKind.PERMANENT)

        binary_err = self._check_binary(target, file_path)
        if binary_err is not None:
            return self._error(args, binary_err, started, error_kind=ErrorKind.PERMANENT)

        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return self._error(args, f"Permission denied: {file_path}", started, error_kind=ErrorKind.PERMANENT)

        offset = args.get("offset", 0)
        limit = args.get("limit", 500)
        lines = text.splitlines()
        sliced = lines[offset:offset + limit]
        content = "\n".join(sliced)

        # Enforce character budget on single file too
        truncated = len(lines) > offset + limit
        if len(content) > self._max_chars:
            content = content[:self._max_chars]
            truncated = True

        return self._success(
            args,
            {
                "path": file_path,
                "content": content,
                "total_lines": len(lines),
                "truncated": truncated,
            },
            started,
        )

    # ------------------------------------------------------------------
    # Batch mode
    # ------------------------------------------------------------------

    async def _read_batch(
        self,
        paths: list[str],
        args: dict[str, Any],
        context: ToolContext,
        workspace: Path,
        started: str,
    ) -> Any:
        limit = args.get("limit", 200)
        files: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        budget_remaining = self._max_chars
        budget_exhausted = False

        for file_path in paths:
            if budget_exhausted:
                errors[file_path] = "Output budget exhausted"
                continue

            target = (workspace / file_path).resolve()

            err = self._validate_target(target, file_path, workspace)
            if err is not None:
                errors[file_path] = err
                continue

            binary_err = self._check_binary(target, file_path)
            if binary_err is not None:
                errors[file_path] = binary_err
                continue

            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except PermissionError:
                errors[file_path] = f"Permission denied: {file_path}"
                continue

            lines = text.splitlines()
            sliced = lines[:limit]
            content = "\n".join(sliced)
            truncated = len(lines) > limit

            # Apply character budget
            if len(content) > budget_remaining:
                content = content[:budget_remaining]
                truncated = True
                budget_exhausted = True

            budget_remaining -= len(content)

            files[file_path] = {
                "content": content,
                "total_lines": len(lines),
                "truncated": truncated,
            }

            if budget_remaining <= 0:
                budget_exhausted = True

        result: dict[str, Any] = {
            "files_read": len(files),
            "files_failed": len(errors),
            "files": files,
        }
        if errors:
            result["errors"] = errors
        if budget_exhausted:
            result["budget_note"] = (
                f"Character budget ({self._max_chars}) exhausted. "
                f"Some files may be truncated or skipped."
            )

        return self._success(args, result, started)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_target(target: Path, file_path: str, workspace: Path) -> str | None:
        """Return an error message if the target is invalid, else None."""
        try:
            target.relative_to(workspace)
        except ValueError:
            return f"Path outside workspace: {target}"
        if not target.exists():
            return f"File not found: {file_path}"
        if not target.is_file():
            return f"Not a file: {file_path}"
        return None

    @staticmethod
    def _check_binary(target: Path, file_path: str) -> str | None:
        """Return an error message if the file appears binary, else None."""
        try:
            raw = target.read_bytes()[:8192]
        except PermissionError:
            return f"Permission denied: {file_path}"
        if b"\x00" in raw:
            return f"Binary file detected: {file_path}"
        return None
