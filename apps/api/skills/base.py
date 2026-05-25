"""skills/base — Abstract base class for all tools."""
from __future__ import annotations
import abc
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine
from pydantic import BaseModel
from apps.api.models.run import ErrorKind, RetryPolicy, RiskLevel, ToolResult
from apps.api.models.tool_manifest import ToolManifest

# Type alias for the delegation callback.
# Signature: (parent_run_id, task, workspace_id, max_iterations) -> Run
DelegateFn = Callable[..., Coroutine[Any, Any, Any]]


class ToolContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    workspace_root: str
    run_id: str = ""
    step_id: str = ""
    db_path: str = ""
    execution_id: str = ""
    delegate_fn: DelegateFn | None = None  # set by orchestrator for delegation


class BaseTool(abc.ABC):
    @abc.abstractmethod
    def manifest(self) -> ToolManifest: ...

    @abc.abstractmethod
    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult: ...

    @property
    def name(self) -> str:
        return self.manifest().name

    # -- ReAct extensions (defaults safe for existing tools) --

    async def validate(self, args: dict[str, Any], context: ToolContext) -> ToolResult | None:
        """Pre-flight validation. Return None if valid, ToolResult with error if invalid."""
        return None

    async def compensate(self, args: dict[str, Any], context: ToolContext, execution_id: str) -> ToolResult:
        """Undo/compensate for a previously executed action. Override for stateful tools."""
        return ToolResult(
            tool_name=self.name, status="not_applicable", input=args,
            started_at=self._now(), finished_at=self._now(),
        )

    @property
    def retry_policy(self) -> RetryPolicy:
        """Override to allow retries for transient failures."""
        return RetryPolicy()

    # -- helpers --

    def _success(self, args: dict[str, Any], output: dict[str, Any], started_at: str, **kw: Any) -> ToolResult:
        m = self.manifest()
        return ToolResult(tool_name=m.name, status="success", risk_level=m.risk_level,
                          input=args, output=output, started_at=started_at,
                          finished_at=datetime.now(timezone.utc).isoformat(), **kw)

    def _error(self, args: dict[str, Any], error: str, started_at: str,
               error_kind: ErrorKind = ErrorKind.PERMANENT) -> ToolResult:
        m = self.manifest()
        return ToolResult(tool_name=m.name, status="error", risk_level=m.risk_level,
                          input=args, error=error, error_kind=error_kind,
                          started_at=started_at,
                          finished_at=datetime.now(timezone.utc).isoformat())

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
