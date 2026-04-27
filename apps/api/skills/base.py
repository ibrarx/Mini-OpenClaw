"""
Base class and shared types for all tools.

Every tool inherits BaseTool, implements ``execute()``, and provides
a ``get_manifest()`` class method so the registry can discover and
describe it without running tool code.
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import Any

import jsonschema as _jsonschema

from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ValidationResult:
    """Result of validating tool args against the input schema."""

    def __init__(self, valid: bool, errors: list[str] | None = None) -> None:
        self.valid = valid
        self.errors = errors or []


class BaseTool(abc.ABC):
    """Abstract base class for all Mini-OpenClaw tools.

    Subclasses must implement ``execute`` and ``get_manifest``.
    """

    @classmethod
    @abc.abstractmethod
    def get_manifest(cls) -> ToolManifest:
        """Return the declarative manifest describing this tool."""
        ...

    @abc.abstractmethod
    async def execute(
        self, args: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        """Execute the tool with validated arguments.

        Args:
            args: Tool-specific arguments matching the input_schema.
            context: Runtime context including ``workspace_root``.

        Returns:
            Structured ToolResult envelope.
        """
        ...

    @classmethod
    def validate_args(cls, args: dict[str, Any]) -> ValidationResult:
        """Validate args against the tool's input_schema using jsonschema."""
        manifest = cls.get_manifest()
        schema = manifest.input_schema
        if not schema:
            return ValidationResult(valid=True)
        errors: list[str] = []
        try:
            _jsonschema.validate(instance=args, schema=schema)
        except _jsonschema.ValidationError as exc:
            errors.append(str(exc.message))
        except _jsonschema.SchemaError as exc:
            errors.append(f"Invalid schema: {exc.message}")
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    # helpers for building ToolResult envelopes
    @classmethod
    def _success(
        cls,
        args: dict[str, Any],
        output: dict[str, Any],
        started_at: str,
        artifacts: list[str] | None = None,
    ) -> ToolResult:
        m = cls.get_manifest()
        return ToolResult(
            tool_name=m.name,
            status="success",
            risk_level=m.risk_level,
            input=args,
            output=output,
            started_at=started_at,
            finished_at=_now_iso(),
            artifacts=artifacts or [],
        )

    @classmethod
    def _error(cls, args: dict[str, Any], error: str, started_at: str) -> ToolResult:
        m = cls.get_manifest()
        return ToolResult(
            tool_name=m.name,
            status="error",
            risk_level=m.risk_level,
            input=args,
            error=error,
            started_at=started_at,
            finished_at=_now_iso(),
        )
