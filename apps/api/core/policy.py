"""core/policy — Policy engine: the hard security boundary."""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from apps.api.models.run import RiskLevel
from apps.api.platform_utils import IS_WINDOWS, get_shell_allowlist

logger = logging.getLogger(__name__)
_UNIX_METACHAR = re.compile(r"[;&|`$(){}]|&&|\|\|")
_WIN_METACHAR = re.compile(r"[&^%]|cmd\s*/c", re.IGNORECASE)
_REDIRECT = re.compile(r"[<>]|>>")
_MOUNT_PREFIX = re.compile(r"^(?P<alias>[A-Za-z0-9_]+):(?P<rest>.*)$")

class PolicyDecision(BaseModel):
    allowed: bool
    classification: str  # safe | approval_required | forbidden
    reason: str = ""

class PolicyEngine:
    def __init__(
        self,
        workspace_root: str | Path,
        mounts: dict[str, tuple[Path, bool]] | None = None,
    ) -> None:
        self._workspace = Path(workspace_root).resolve()
        self._mounts = mounts or {}   # alias -> (path, read_only)
        self._shell_allowlist = get_shell_allowlist()

    @property
    def workspace_root(self) -> Path:
        return self._workspace

    @property
    def mounts(self) -> dict[str, tuple[Path, bool]]:
        return self._mounts

    def resolve_root(self, path: str) -> tuple[Path, Path, bool]:
        """Return (root, resolved_target, read_only) for a path.

        If the path has a ``name:rest`` prefix and the alias is a known mount,
        ``rest`` is resolved against that mount's root. Otherwise the full path
        resolves against the primary workspace.

        Raises ``ValueError`` if the alias matches the prefix pattern but is
        unknown (because ``:`` is typically invalid in filenames).
        """
        m = _MOUNT_PREFIX.match(path)
        if m:
            alias = m.group("alias")
            rest = m.group("rest")
            if alias in self._mounts:
                root, read_only = self._mounts[alias]
                target = (root / rest).resolve()
                return root, target, read_only
            # Alias pattern matched but unknown name → forbidden.
            # Colon is invalid in filenames on Windows and unusual on Unix,
            # so treating an unknown alias as a literal filename is risky.
            raise ValueError(f"Unknown mount alias: {alias!r}")

        # No prefix — primary workspace (never read-only)
        target = (self._workspace / path).resolve()
        return self._workspace, target, False

    def validate_path(self, path: str, *, write: bool = False) -> PolicyDecision:
        if not path or not path.strip():
            return PolicyDecision(allowed=False, classification="forbidden", reason="Empty path")
        # Block tilde expansion attempts
        if path.startswith("~"):
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason="Home directory expansion not allowed")
        try:
            root, target, read_only = self.resolve_root(path)
        except ValueError as exc:
            return PolicyDecision(allowed=False, classification="forbidden", reason=str(exc))
        except OSError as exc:
            return PolicyDecision(allowed=False, classification="forbidden", reason=f"Invalid path: {exc}")
        try:
            target.relative_to(root)
        except ValueError:
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason=f"Path {target} is outside workspace {root}")
        if write:
            if read_only:
                return PolicyDecision(
                    allowed=False, classification="forbidden",
                    reason=f"Mount is read-only",
                )
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

    # ── URL / network policy ─────────────────────────────────

    def validate_url(self, url: str, allowed_domains: list[str]) -> PolicyDecision:
        """Validate a URL for fetch_url.  Returns a PolicyDecision.

        Checks (fail-closed on any):
        1. Valid URL with http/https scheme
        2. Host present
        3. Host (or parent domain) in allowed_domains; empty list = forbidden
        4. Resolved IPs are not private/loopback/link-local/reserved/multicast
        """
        # Parse
        try:
            parsed = urlparse(url)
        except Exception:
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason="URL failed to parse")

        # Scheme
        if parsed.scheme not in ("http", "https"):
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason=f"Scheme '{parsed.scheme}' not allowed (http/https only)")

        # Host present
        host = parsed.hostname
        if not host:
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason="No host in URL")

        # Domain allowlist
        if not allowed_domains:
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason="No domains in allowlist — web fetch is opt-in")

        if not self._domain_allowed(host, allowed_domains):
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason=f"Host '{host}' not in allowed domains")

        # SSRF defense: resolve hostname and reject private IPs
        try:
            resolved = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            return PolicyDecision(allowed=False, classification="forbidden",
                                  reason=f"DNS resolution failed for '{host}'")

        for family, _type, _proto, _canonname, sockaddr in resolved:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                return PolicyDecision(allowed=False, classification="forbidden",
                                      reason=f"Invalid resolved IP: {ip_str}")

            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return PolicyDecision(allowed=False, classification="forbidden",
                                      reason=f"Host '{host}' resolves to non-public IP {ip_str}")

            # Explicit cloud metadata IP block
            if ip_str == "169.254.169.254":
                return PolicyDecision(allowed=False, classification="forbidden",
                                      reason=f"Host '{host}' resolves to cloud metadata IP")

        return PolicyDecision(allowed=True, classification="approval_required",
                              reason=f"URL allowed (host '{host}' in allowlist)")

    @staticmethod
    def _domain_allowed(host: str, allowed_domains: list[str]) -> bool:
        """Check if host matches or is a subdomain of any allowed domain."""
        host = host.lower().rstrip(".")
        for domain in allowed_domains:
            domain = domain.lower().rstrip(".")
            if host == domain or host.endswith("." + domain):
                return True
        return False
