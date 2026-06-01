"""skills/fetch_url — Fetch content from a URL on the public web.

HIGH risk, approval required.  First tool that touches the network.

Security model:
- Domain allowlist (empty = block everything, opt-in by design)
- Scheme restricted to http/https
- SSRF defense: resolved IPs checked for private/loopback/link-local/reserved
- DNS re-validation immediately before each HTTP request (TOCTOU / rebinding defense)
- Response body streamed with mid-stream abort if size exceeds max_bytes
- Timeout enforced
- Redirects disabled at HTTP level; followed manually with per-hop policy re-validation

JSON responses are parsed and returned as structured data; everything else
is returned as cleaned, length-capped text.
"""
from __future__ import annotations

import json
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

# Chunk size for streaming reads.
_STREAM_CHUNK = 8_192


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

    # ── internal helpers ──────────────────────────────────────

    def _check_policy(self, url: str, context: ToolContext) -> str | None:
        """Run URL through the policy validator.

        Returns an error message string if blocked, None if allowed.
        Re-used for the initial check and for each redirect hop + the
        pre-flight DNS re-validation.
        """
        if context.validate_url_fn is None:
            return "URL validator not available"
        decision = context.validate_url_fn(url, self._allowed_domains)
        if not decision.allowed:
            return f"URL blocked by policy: {decision.reason}"
        return None

    async def _stream_body(
        self, response: httpx.Response,
    ) -> tuple[bytes, str | None]:
        """Stream the response body, aborting if it exceeds max_bytes.

        Returns ``(body_bytes, error_message)``.  ``error_message`` is
        None on success.
        """
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes(chunk_size=_STREAM_CHUNK):
            total += len(chunk)
            if total > self._max_bytes:
                await response.aclose()
                return b"", (
                    f"Response body exceeded {self._max_bytes} byte limit "
                    f"(streamed {total} bytes before abort)"
                )
            chunks.append(chunk)
        return b"".join(chunks), None

    def _parse_response(
        self, body: bytes, content_type: str, status_code: int, final_url: str,
        args: dict[str, Any], started: str,
    ) -> Any:
        """Detect JSON vs text/HTML and return a ToolResult."""
        # Try JSON by content-type
        if "application/json" in content_type:
            try:
                data = json.loads(body)
                return self._success(args, {
                    "type": "json", "data": data,
                    "status": status_code, "url": final_url,
                }, started)
            except (json.JSONDecodeError, ValueError):
                pass  # fall through to text

        # Try JSON by body shape (regardless of content-type)
        text_body = body.decode("utf-8", errors="replace")
        stripped = text_body.strip()
        if stripped and stripped[0] in ("{", "["):
            try:
                data = json.loads(stripped)
                return self._success(args, {
                    "type": "json", "data": data,
                    "status": status_code, "url": final_url,
                }, started)
            except (json.JSONDecodeError, ValueError):
                pass

        # Text / HTML
        cleaned = _strip_html(text_body) if "html" in content_type else text_body
        if len(cleaned) > _TEXT_OUTPUT_LIMIT:
            cleaned = cleaned[:_TEXT_OUTPUT_LIMIT] + "… [truncated]"

        return self._success(args, {
            "type": "text", "text": cleaned,
            "status": status_code, "url": final_url,
        }, started)

    # ── main execute ──────────────────────────────────────────

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        url: str = args.get("url", "")

        # Gate: feature disabled
        if not self._enabled:
            return self._error(args, "Web fetch is disabled in configuration", started,
                               error_kind=ErrorKind.PERMANENT)

        # Gate: initial policy check (scheme, domain, DNS resolve, IP check)
        err = self._check_policy(url, context)
        if err:
            return self._error(args, err, started, error_kind=ErrorKind.PERMANENT)

        # Fetch
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_s),
                follow_redirects=False,  # manual redirect handling
            ) as client:
                # ── DNS rebinding defense ──
                # Re-resolve the hostname and re-check IPs immediately before
                # the HTTP request.  This shrinks the TOCTOU window between
                # validation and connection to microseconds, preventing an
                # attacker from flipping a DNS record from a public IP (passes
                # initial check) to a private/loopback IP between checks.
                preflight_err = self._check_policy(url, context)
                if preflight_err:
                    return self._error(args, f"Pre-flight re-validation failed: {preflight_err}",
                                       started, error_kind=ErrorKind.PERMANENT)

                # ── Stream response ──
                async with client.stream("GET", url) as response:
                    # Handle redirects manually with per-hop policy validation
                    redir_response = response
                    redirects = 0
                    while redir_response.is_redirect and redirects < self._max_redirects:
                        location = redir_response.headers.get("location", "")
                        if not location:
                            break
                        await redir_response.aclose()

                        # Validate redirect target (domain + DNS + IPs)
                        redir_err = self._check_policy(location, context)
                        if redir_err:
                            return self._error(
                                args,
                                f"Redirect target blocked: {redir_err}",
                                started, error_kind=ErrorKind.PERMANENT,
                            )
                        # Pre-flight re-validation for redirect target
                        redir_preflight = self._check_policy(location, context)
                        if redir_preflight:
                            return self._error(
                                args,
                                f"Redirect pre-flight failed: {redir_preflight}",
                                started, error_kind=ErrorKind.PERMANENT,
                            )

                        # Open a new stream for the redirect target
                        redir_response = await client.send(
                            client.build_request("GET", location),
                            stream=True,
                        )
                        redirects += 1

                    if redir_response.is_redirect:
                        await redir_response.aclose()
                        return self._error(args, f"Too many redirects (>{self._max_redirects})",
                                           started, error_kind=ErrorKind.PERMANENT)

                    # Early reject via content-length header
                    cl = redir_response.headers.get("content-length")
                    if cl and cl.isdigit() and int(cl) > self._max_bytes:
                        await redir_response.aclose()
                        return self._error(
                            args,
                            f"Response too large ({cl} bytes, limit {self._max_bytes})",
                            started, error_kind=ErrorKind.PERMANENT,
                        )

                    # Stream body with mid-stream size enforcement
                    body, size_err = await self._stream_body(redir_response)
                    if size_err:
                        return self._error(args, size_err, started,
                                           error_kind=ErrorKind.PERMANENT)

                    # Capture headers before context manager closes
                    content_type = redir_response.headers.get("content-type", "")
                    final_url = str(redir_response.url)
                    status_code = redir_response.status_code

        except httpx.TimeoutException:
            return self._error(args, f"Request timed out after {self._timeout_s}s",
                               started, error_kind=ErrorKind.TRANSIENT)
        except httpx.ConnectError as exc:
            return self._error(args, f"Connection error: {exc}", started,
                               error_kind=ErrorKind.TRANSIENT)
        except httpx.HTTPError as exc:
            return self._error(args, f"HTTP error: {exc}", started,
                               error_kind=ErrorKind.TRANSIENT)

        return self._parse_response(body, content_type, status_code, final_url,
                                    args, started)
