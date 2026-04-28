"""core/policy — Policy engine: the hard security boundary."""
import logging, re
from pathlib import Path
from pydantic import BaseModel
from apps.api.models.run import RiskLevel
from apps.api.platform_utils import IS_WINDOWS, get_shell_allowlist

logger = logging.getLogger(__name__)
_UNIX_METACHAR = re.compile(r"[;&|`$(){}]|&&|\|\|")
_WIN_METACHAR = re.compile(r"[&^%]|cmd\s*/c", re.IGNORECASE)
_REDIRECT = re.compile(r"[<>]|>>")

class PolicyDecision(BaseModel):
    allowed: bool
    classification: str  # safe | approval_required | forbidden
    reason: str = ""

class PolicyEngine:
    def __init__(self, workspace_root: str | Path) -> None:
        self._workspace = Path(workspace_root).resolve()
        self._shell_allowlist = get_shell_allowlist()

    @property
    def workspace_root(self) -> Path:
        return self._workspace

    def validate_path(self, path: str, *, write: bool = False) -> PolicyDecision:
        if not path or not path.strip():
            return PolicyDecision(allowed=False, classification="forbidden", reason="Empty path")
        # Block tilde expansion attempts
        if path.startswith("~"):
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason="Home directory expansion not allowed")
        try:
            target = (self._workspace / path).resolve()
        except (ValueError, OSError) as exc:
            return PolicyDecision(allowed=False, classification="forbidden", reason=f"Invalid path: {exc}")
        try:
            target.relative_to(self._workspace)
        except ValueError:
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason=f"Path {target} is outside workspace {self._workspace}")
        if write:
            return PolicyDecision(allowed=True, classification="approval_required",
                                  reason="Write operations require approval")
        return PolicyDecision(allowed=True, classification="safe", reason="Path within workspace")

    def validate_shell(self, command: str, args: list[str]) -> PolicyDecision:
        if not command or not command.strip():
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason="Empty command")
        if command not in self._shell_allowlist:
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason=f"Command '{command}' not in allowlist")
        all_args = " ".join(args)
        if _UNIX_METACHAR.search(all_args):
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason=f"Shell metacharacters detected: {all_args}")
        if _REDIRECT.search(all_args):
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason=f"Redirect operators detected: {all_args}")
        # Check Windows metacharacters on all platforms for consistency
        if _WIN_METACHAR.search(all_args):
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason=f"Dangerous metacharacters detected: {all_args}")
        for arg in args:
            if ".." in arg:
                return PolicyDecision(allowed=False, classification="forbidden",
                                      reason=f"Path traversal detected: {arg}")
        return PolicyDecision(allowed=True, classification="approval_required",
                              reason=f"Shell command '{command}' requires approval")

    def classify_tool(self, tool_name: str, risk_level: str, approval_required: bool) -> PolicyDecision:
        if risk_level == "high":
            return PolicyDecision(allowed=True, classification="approval_required",
                                  reason=f"Tool {tool_name} has high risk level")
        if approval_required:
            return PolicyDecision(allowed=True, classification="approval_required",
                                  reason=f"Tool {tool_name} requires approval")
        return PolicyDecision(allowed=True, classification="safe",
                              reason=f"Tool {tool_name} is safe")
