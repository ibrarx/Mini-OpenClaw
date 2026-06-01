"""tests/test_fetch — Tests for the fetch_url tool and URL policy validation.

All HTTP calls are mocked — no real network traffic.
"""
from __future__ import annotations

import socket
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from apps.api.core.policy import PolicyDecision, PolicyEngine
from apps.api.models.run import ErrorKind, RiskLevel
from apps.api.skills.base import ToolContext
from apps.api.skills.fetch_url import FetchUrlTool, _STREAM_CHUNK

# ─── Fixtures ────────────────────────────────────────────────────

WORKSPACE = "/tmp/test-workspace"
ALLOWED = ["api.open-meteo.com", "example.com"]


@pytest.fixture
def policy() -> PolicyEngine:
    return PolicyEngine(workspace_root=WORKSPACE)


@pytest.fixture
def tool() -> FetchUrlTool:
    return FetchUrlTool(
        allowed_domains=ALLOWED,
        max_bytes=1024,
        timeout_s=5.0,
        max_redirects=2,
    )


@pytest.fixture
def ctx(policy: PolicyEngine) -> ToolContext:
    return ToolContext(
        workspace_root=WORKSPACE,
        run_id="test-run",
        step_id="step-1",
        validate_url_fn=policy.validate_url,
    )


def _mock_getaddrinfo_public(*_args: Any, **_kw: Any) -> list:
    """Return a public IP for any hostname."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


def _mock_getaddrinfo_private(*_args: Any, **_kw: Any) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))]


def _mock_getaddrinfo_loopback(*_args: Any, **_kw: Any) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]


def _mock_getaddrinfo_metadata(*_args: Any, **_kw: Any) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _mock_getaddrinfo_link_local(*_args: Any, **_kw: Any) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.1.1", 0))]


# ─── Streaming response helper ──────────────────────────────────

class MockStreamResponse:
    """Mimics an httpx.Response opened in streaming mode."""

    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
        url: str = "https://example.com",
        is_redirect: bool = False,
    ) -> None:
        self.status_code = status_code
        self._content = content
        self.headers = headers or {}
        self.url = httpx.URL(url)
        self.is_redirect = is_redirect
        self._closed = False

    async def aiter_bytes(self, chunk_size: int = 8192) -> AsyncIterator[bytes]:
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]

    async def aclose(self) -> None:
        self._closed = True

    async def __aenter__(self) -> "MockStreamResponse":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()


def _patch_stream(response: MockStreamResponse):
    """Return a patch that makes httpx.AsyncClient.stream yield *response*."""
    @asynccontextmanager
    async def _fake_stream(*_a: Any, **_kw: Any):
        yield response

    return patch.object(httpx.AsyncClient, "stream", _fake_stream)


# ─── PolicyEngine.validate_url tests ────────────────────────────

class TestValidateUrl:

    def test_allowed_domain_public_ip(self, policy: PolicyEngine) -> None:
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public):
            d = policy.validate_url("https://api.open-meteo.com/v1/forecast", ALLOWED)
        assert d.allowed is True
        assert d.classification == "approval_required"

    def test_subdomain_allowed(self, policy: PolicyEngine) -> None:
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public):
            d = policy.validate_url("https://sub.example.com/path", ALLOWED)
        assert d.allowed is True

    def test_domain_not_in_allowlist(self, policy: PolicyEngine) -> None:
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public):
            d = policy.validate_url("https://evil.com/steal", ALLOWED)
        assert d.allowed is False
        assert "not in allowed" in d.reason

    def test_empty_allowlist_blocks_everything(self, policy: PolicyEngine) -> None:
        d = policy.validate_url("https://example.com", [])
        assert d.allowed is False
        assert "opt-in" in d.reason

    def test_file_scheme_forbidden(self, policy: PolicyEngine) -> None:
        d = policy.validate_url("file:///etc/passwd", ALLOWED)
        assert d.allowed is False
        assert "Scheme" in d.reason

    def test_ftp_scheme_forbidden(self, policy: PolicyEngine) -> None:
        d = policy.validate_url("ftp://example.com/file", ALLOWED)
        assert d.allowed is False

    def test_no_host(self, policy: PolicyEngine) -> None:
        d = policy.validate_url("https://", ALLOWED)
        assert d.allowed is False
        assert "No host" in d.reason

    def test_private_ip_blocked(self, policy: PolicyEngine) -> None:
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_private):
            d = policy.validate_url("https://example.com/api", ALLOWED)
        assert d.allowed is False
        assert "non-public" in d.reason

    def test_loopback_ip_blocked(self, policy: PolicyEngine) -> None:
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_loopback):
            d = policy.validate_url("https://example.com/api", ALLOWED)
        assert d.allowed is False
        assert "non-public" in d.reason

    def test_metadata_ip_blocked(self, policy: PolicyEngine) -> None:
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_metadata):
            d = policy.validate_url("https://example.com/api", ALLOWED)
        assert d.allowed is False

    def test_link_local_ip_blocked(self, policy: PolicyEngine) -> None:
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_link_local):
            d = policy.validate_url("https://example.com/api", ALLOWED)
        assert d.allowed is False

    def test_dns_failure(self, policy: PolicyEngine) -> None:
        def _fail(*a: Any, **kw: Any) -> list:
            raise socket.gaierror("Name resolution failed")
        with patch("apps.api.core.policy.socket.getaddrinfo", _fail):
            d = policy.validate_url("https://example.com/api", ALLOWED)
        assert d.allowed is False
        assert "DNS" in d.reason

    def test_invalid_url(self, policy: PolicyEngine) -> None:
        d = policy.validate_url("not-a-url", ALLOWED)
        assert d.allowed is False


# ─── FetchUrlTool.execute tests ──────────────────────────────────

class TestFetchUrlTool:

    @pytest.mark.asyncio
    async def test_json_response(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        resp = MockStreamResponse(
            200, b'{"temperature": 22, "unit": "celsius"}',
            {"content-type": "application/json"},
            url="https://api.open-meteo.com/v1/forecast",
        )
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             _patch_stream(resp):
            result = await tool.execute({"url": "https://api.open-meteo.com/v1/forecast"}, ctx)
        assert result.status == "success"
        assert result.output["type"] == "json"
        assert result.output["data"]["temperature"] == 22
        assert result.output["status"] == 200

    @pytest.mark.asyncio
    async def test_html_response(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        resp = MockStreamResponse(
            200, b"<html><body><h1>Hello</h1><p>World</p></body></html>",
            {"content-type": "text/html; charset=utf-8"},
            url="https://example.com/page",
        )
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             _patch_stream(resp):
            result = await tool.execute({"url": "https://example.com/page"}, ctx)
        assert result.status == "success"
        assert result.output["type"] == "text"
        assert "Hello" in result.output["text"]
        assert "World" in result.output["text"]
        assert "<h1>" not in result.output["text"]

    @pytest.mark.asyncio
    async def test_domain_not_allowed(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public):
            result = await tool.execute({"url": "https://evil.com/steal"}, ctx)
        assert result.status == "error"
        assert "blocked by policy" in result.error

    @pytest.mark.asyncio
    async def test_empty_allowlist_blocks(self, ctx: ToolContext) -> None:
        tool = FetchUrlTool(allowed_domains=[], max_bytes=1024, timeout_s=5.0, max_redirects=2)
        result = await tool.execute({"url": "https://example.com"}, ctx)
        assert result.status == "error"
        assert "blocked by policy" in result.error

    @pytest.mark.asyncio
    async def test_file_scheme_blocked(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        result = await tool.execute({"url": "file:///etc/passwd"}, ctx)
        assert result.status == "error"
        assert "Scheme" in result.error or "blocked" in result.error

    @pytest.mark.asyncio
    async def test_private_ip_blocked(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_private):
            result = await tool.execute({"url": "https://example.com/api"}, ctx)
        assert result.status == "error"
        assert "non-public" in result.error or "blocked" in result.error

    @pytest.mark.asyncio
    async def test_loopback_blocked(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_loopback):
            result = await tool.execute({"url": "https://example.com/api"}, ctx)
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_response_too_large_streamed(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        """Body exceeds max_bytes mid-stream — aborted without reading everything."""
        big_body = b"x" * 2000  # tool max_bytes is 1024
        resp = MockStreamResponse(200, big_body, {"content-type": "text/plain"},
                                  url="https://example.com/big")
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             _patch_stream(resp):
            result = await tool.execute({"url": "https://example.com/big"}, ctx)
        assert result.status == "error"
        assert "limit" in result.error.lower() or "exceeded" in result.error.lower()

    @pytest.mark.asyncio
    async def test_content_length_header_rejects_early(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        """content-length header alone triggers early rejection before streaming."""
        resp = MockStreamResponse(
            200, b"small",
            {"content-type": "text/plain", "content-length": "999999999"},
            url="https://example.com/big",
        )
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             _patch_stream(resp):
            result = await tool.execute({"url": "https://example.com/big"}, ctx)
        assert result.status == "error"
        assert "large" in result.error.lower() or "limit" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        @asynccontextmanager
        async def _raise_timeout(*_a: Any, **_kw: Any):
            raise httpx.ReadTimeout("timed out")
            yield  # pragma: no cover — makes it a generator

        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             patch.object(httpx.AsyncClient, "stream", _raise_timeout):
            result = await tool.execute({"url": "https://example.com/slow"}, ctx)
        assert result.status == "error"
        assert result.error_kind == ErrorKind.TRANSIENT
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_disabled(self, ctx: ToolContext) -> None:
        tool = FetchUrlTool(allowed_domains=ALLOWED, max_bytes=1024, timeout_s=5.0,
                            max_redirects=2, enabled=False)
        result = await tool.execute({"url": "https://example.com"}, ctx)
        assert result.status == "error"
        assert "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_validator(self, tool: FetchUrlTool) -> None:
        ctx_no_validator = ToolContext(workspace_root=WORKSPACE, run_id="r", step_id="s")
        result = await tool.execute({"url": "https://example.com"}, ctx_no_validator)
        assert result.status == "error"
        assert "validator" in result.error.lower()

    @pytest.mark.asyncio
    async def test_json_autodetect_without_content_type(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        """JSON body detected even when content-type is text/plain."""
        resp = MockStreamResponse(
            200, b'{"key": "value"}',
            {"content-type": "text/plain"},
            url="https://example.com/data",
        )
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             _patch_stream(resp):
            result = await tool.execute({"url": "https://example.com/data"}, ctx)
        assert result.status == "success"
        assert result.output["type"] == "json"
        assert result.output["data"]["key"] == "value"

    @pytest.mark.asyncio
    async def test_dns_rebinding_blocked(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        """DNS flips from public to private between initial check and pre-flight.

        The initial validate_url sees a public IP and passes.  The pre-flight
        re-validation (immediately before the HTTP request) sees a private IP
        and blocks — closing the TOCTOU window.
        """
        call_count = 0

        def _flip_dns(*_a: Any, **_kw: Any) -> list:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                # First call (initial check): public → passes
                return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]
            # Second call (pre-flight): private → should block
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))]

        with patch("apps.api.core.policy.socket.getaddrinfo", _flip_dns):
            result = await tool.execute({"url": "https://example.com/api"}, ctx)
        assert result.status == "error"
        assert "pre-flight" in result.error.lower() or "non-public" in result.error.lower()

    def test_manifest(self, tool: FetchUrlTool) -> None:
        m = tool.manifest()
        assert m.name == "fetch_url"
        assert m.risk_level == RiskLevel.HIGH
        assert m.approval_required is True

    def test_retry_policy(self, tool: FetchUrlTool) -> None:
        rp = tool.retry_policy
        assert rp.max_retries == 1
        assert rp.idempotent is True
