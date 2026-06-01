"""skills/fetch_url — Fetch content from a URL on the public web.

HIGH risk, approval required.  First tool that touches the network.

Security model:
- Domain allowlist (empty = block everything, opt-in by design)
- Scheme restricted to http/https
- SSRF defense: resolved IPs checked for private/loopback/link-local/reserved
- Response size capped at max_bytes
- Timeout enforced
- Redirects disabled to prevent DNS rebinding (resolve-time IP check stays valid)

JSON responses are parsed and returned as structured data; everything else
is returned as cleaned, length-capped text.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from apps.api.models.run import ErrorKind, RetryPolicy, RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)

# Simple HTML tag stripper — used when beautifulsoup4 is unavailable.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s{2,}")

# Maximum chars of cleaned text returned in the output.
_TEXT_OUTPUT_LIMIT = 8_000


def _strip_html(html: str) -> str:
    """Best-effort HTML-to-text.  Uses beautifulsoup4 if installed, else regex."""
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-untyped]
        soup = BeautifulSoup(html, "html.parser")
        # Remove script/style elements entirely
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
    except ImportError:
        text = _TAG_RE.sub(" ", html)
    return _WS_RE.sub(" ", text).strip()


class FetchUrlTool(BaseTool):
    """Fetch content from a public URL with allowlist + SSRF guards."""

    def __init__(
        self,
        *,
        allowed_domains: list[str],
        max_bytes: int = 1_048_576,
        timeout_s: float = 10.0,
        max_redirects: int = 3,
        enabled: bool = True,
    ) -> None:
        self._allowed_domains = allowed_domains
        self._max_bytes = max_bytes
        self._timeout_s = timeout_s
        self._max_redirects = max_redirects
        self._enabled = enabled

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="fetch_url",
            description=(
                "Fetch content from a URL on the public web. "
                "Returns parsed JSON for API responses, or cleaned text for web pages. "
                "Use for live information like weather, public data, or documentation."
            ),
            risk_level=RiskLevel.HIGH,
            approval_required=True,
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        )

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_retries=1, idempotent=True)

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        url: str = args.get("url", "")

        # Gate: feature disabled
        if not self._enabled:
            return self._error(args, "Web fetch is disabled in configuration", started,
                               error_kind=ErrorKind.PERMANENT)

        # Gate: URL policy validation through the shared validator
        if context.validate_url_fn is None:
            return self._error(args, "URL validator not available", started,
                               error_kind=ErrorKind.PERMANENT)

        decision = context.validate_url_fn(url, self._allowed_domains)
        if not decision.allowed:
            return self._error(args, f"URL blocked by policy: {decision.reason}", started,
                               error_kind=ErrorKind.PERMANENT)

        # Fetch
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_s),
                follow_redirects=False,  # disabled to prevent DNS rebinding
            ) as client:
                response = await client.get(url)

                # Handle redirects manually with count limit
                redirects = 0
                while response.is_redirect and redirects < self._max_redirects:
                    location = response.headers.get("location", "")
                    if not location:
                        break
                    # Re-validate the redirect target through policy
                    redirect_decision = context.validate_url_fn(location, self._allowed_domains)
                    if not redirect_decision.allowed:
                        return self._error(
                            args,
                            f"Redirect target blocked by policy: {redirect_decision.reason}",
                            started, error_kind=ErrorKind.PERMANENT,
                        )
                    response = await client.get(location)
                    redirects += 1

                if response.is_redirect:
                    return self._error(args, f"Too many redirects (>{self._max_redirects})",
                                       started, error_kind=ErrorKind.PERMANENT)

                # Size check
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self._max_bytes:
                    return self._error(
                        args,
                        f"Response too large ({content_length} bytes, limit {self._max_bytes})",
                        started, error_kind=ErrorKind.PERMANENT,
                    )

                body = response.content
                if len(body) > self._max_bytes:
                    return self._error(
                        args,
                        f"Response body exceeded {self._max_bytes} byte limit",
                        started, error_kind=ErrorKind.PERMANENT,
                    )

        except httpx.TimeoutException:
            return self._error(args, f"Request timed out after {self._timeout_s}s",
                               started, error_kind=ErrorKind.TRANSIENT)
        except httpx.ConnectError as exc:
            return self._error(args, f"Connection error: {exc}", started,
                               error_kind=ErrorKind.TRANSIENT)
        except httpx.HTTPError as exc:
            return self._error(args, f"HTTP error: {exc}", started,
                               error_kind=ErrorKind.TRANSIENT)

        # Detect content type and build output
        content_type = response.headers.get("content-type", "")
        final_url = str(response.url)
        status_code = response.status_code

        # Try JSON
        if "application/json" in content_type:
            try:
                data = response.json()
                return self._success(args, {
                    "type": "json",
                    "data": data,
                    "status": status_code,
                    "url": final_url,
                }, started)
            except Exception:
                pass  # fall through to text handling

        # Also try JSON if body looks like JSON regardless of content-type
        text_body = body.decode("utf-8", errors="replace")
        stripped = text_body.strip()
        if stripped and stripped[0] in ("{", "["):
            try:
                import json
                data = json.loads(stripped)
                return self._success(args, {
                    "type": "json",
                    "data": data,
                    "status": status_code,
                    "url": final_url,
                }, started)
            except (json.JSONDecodeError, ValueError):
                pass

        # Text / HTML
        if "html" in content_type:
            cleaned = _strip_html(text_body)
        else:
            cleaned = text_body

        # Truncate
        if len(cleaned) > _TEXT_OUTPUT_LIMIT:
            cleaned = cleaned[:_TEXT_OUTPUT_LIMIT] + "… [truncated]"

        return self._success(args, {
            "type": "text",
            "text": cleaned,
            "status": status_code,
            "url": final_url,
        }, started)
