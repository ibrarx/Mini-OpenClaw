"""skills/base — Abstract base class for all tools."""
from __future__ import annotations
import abc
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel
from apps.api.models.run import RiskLevel, ToolResult
from apps.api.models.tool_manifest import ToolManifest

class ToolContext(BaseModel):
    workspace_root: str
    run_id: str = ""
    step_id: str = ""
    db_path: str = ""

class BaseTool(abc.ABC):
    @abc.abstractmethod
    def manifest(self) -> ToolManifest: ...

    @abc.abstractmethod
    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult: ...

    @property
    def name(self) -> str:
        return self.manifest().name

    def _success(self, args: dict[str, Any], output: dict[str, Any], started_at: str, **kw: Any) -> ToolResult:
        m = self.manifest()
        return ToolResult(tool_name=m.name, status="success", risk_level=m.risk_level,
                          input=args, output=output, started_at=started_at,
                          finished_at=datetime.now(timezone.utc).isoformat(), **kw)

    def _error(self, args: dict[str, Any], error: str, started_at: str) -> ToolResult:
        m = self.manifest()
        return ToolResult(tool_name=m.name, status="error", risk_level=m.risk_level,
                          input=args, error=error, started_at=started_at,
                          finished_at=datetime.now(timezone.utc).isoformat())

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
