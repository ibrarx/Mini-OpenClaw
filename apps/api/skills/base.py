"""
Base tool interface that all V1 tools must implement.

Provides:
- Abstract methods for manifest and execution
- JSON schema validation via jsonschema
- Structured ToolResult envelope construction helpers
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import jsonschema

from ..models.tool_manifest import (
    ExecutionContext,
    RiskLevel,
    ToolManifest,
    ToolResult,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """
    Abstract base class for all Mini-OpenClaw tools.

    Subclasses must implement get_manifest() and execute().
    """

    @abstractmethod
    def get_manifest(self) -> ToolManifest:
        """Return the tool's declarative manifest."""
        ...

    @abstractmethod
    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        """
        Execute the tool with validated arguments.

        Args:
            args: Tool-specific arguments matching the input schema.
            context: Runtime context (workspace root, session, etc.).

        Returns:
            ToolResult envelope with status, output/error, and timing.
        """
        ...

    def validate_args(self, args: dict[str, Any]) -> ValidationResult:
        """
        Validate args against the tool's input_schema using jsonschema.

        Returns:
            ValidationResult with valid flag and any error messages.
        """
        manifest = self.get_manifest()
        schema = manifest.input_schema
        if not schema:
            return ValidationResult(valid=True)

        errors: list[str] = []
        try:
            jsonschema.validate(instance=args, schema=schema)
        except jsonschema.ValidationError as exc:
            errors.append(str(exc.message))
        except jsonschema.SchemaError as exc:
            errors.append(f"Invalid schema: {exc.message}")

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    # ------------------------------------------------------------------
    # Helpers for building ToolResult envelopes
    # ------------------------------------------------------------------

    def _success(
        self,
        args: dict[str, Any],
        output: dict[str, Any],
        started_at: str,
        artifacts: list[str] | None = None,
    ) -> ToolResult:
        """Build a success ToolResult."""
        manifest = self.get_manifest()
        return ToolResult(
            tool_name=manifest.name,
            status="success",
            risk_level=manifest.risk_level,
            input=args,
            output=output,
            started_at=started_at,
            finished_at=_now_iso(),
            artifacts=artifacts or [],
        )

    def _error(
        self,
        args: dict[str, Any],
        error: str,
        started_at: str,
    ) -> ToolResult:
        """Build an error ToolResult."""
        manifest = self.get_manifest()
        return ToolResult(
            tool_name=manifest.name,
            status="error",
            risk_level=manifest.risk_level,
            input=args,
            error=error,
            started_at=started_at,
            finished_at=_now_iso(),
        )


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
