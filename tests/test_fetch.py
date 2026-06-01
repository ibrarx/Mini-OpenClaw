"""tests/test_fetch — Tests for the fetch_url tool and URL policy validation.

All HTTP calls are mocked — no real network traffic.
"""
from __future__ import annotations

import socket
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from apps.api.core.policy import PolicyDecision, PolicyEngine
from apps.api.models.run import ErrorKind, RiskLevel
from apps.api.skills.base import ToolContext
from apps.api.skills.fetch_url import FetchUrlTool

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
    """Return a private 10.x IP for any hostname."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))]


def _mock_getaddrinfo_loopback(*_args: Any, **_kw: Any) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]


def _mock_getaddrinfo_metadata(*_args: Any, **_kw: Any) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _mock_getaddrinfo_link_local(*_args: Any, **_kw: Any) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.1.1", 0))]


# ─── PolicyEngine.validate_url tests ────────────────────────────

class TestValidateUrl:
    """Unit tests for PolicyEngine.validate_url()."""

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
    """Integration-level tests for the tool (HTTP mocked via httpx transport)."""

    @pytest.mark.asyncio
    async def test_json_response(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        json_body = b'{"temperature": 22, "unit": "celsius"}'
        mock_response = httpx.Response(
            200, content=json_body,
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
        )
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await tool.execute({"url": "https://api.open-meteo.com/v1/forecast"}, ctx)
        assert result.status == "success"
        assert result.output["type"] == "json"
        assert result.output["data"]["temperature"] == 22
        assert result.output["status"] == 200

    @pytest.mark.asyncio
    async def test_html_response(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        html = b"<html><body><h1>Hello</h1><p>World</p></body></html>"
        mock_response = httpx.Response(
            200, content=html,
            headers={"content-type": "text/html; charset=utf-8"},
            request=httpx.Request("GET", "https://example.com/page"),
        )
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await tool.execute({"url": "https://example.com/page"}, ctx)
        assert result.status == "success"
        assert result.output["type"] == "text"
        assert "Hello" in result.output["text"]
        assert "World" in result.output["text"]
        # Tags should be stripped
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
    async def test_response_too_large(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        # Tool max_bytes is 1024
        big_body = b"x" * 2000
        mock_response = httpx.Response(
            200, content=big_body,
            headers={"content-type": "text/plain"},
            request=httpx.Request("GET", "https://example.com/big"),
        )
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await tool.execute({"url": "https://example.com/big"}, ctx)
        assert result.status == "error"
        assert "limit" in result.error.lower() or "large" in result.error.lower()

    @pytest.mark.asyncio
    async def test_content_length_too_large(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        mock_response = httpx.Response(
            200, content=b"small",
            headers={"content-type": "text/plain", "content-length": "999999999"},
            request=httpx.Request("GET", "https://example.com/big"),
        )
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await tool.execute({"url": "https://example.com/big"}, ctx)
        assert result.status == "error"
        assert "large" in result.error.lower() or "limit" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout(self, tool: FetchUrlTool, ctx: ToolContext) -> None:
        async def _raise_timeout(*a: Any, **kw: Any) -> None:
            raise httpx.ReadTimeout("timed out")
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             patch("httpx.AsyncClient.get", side_effect=_raise_timeout):
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
        json_body = b'{"key": "value"}'
        mock_response = httpx.Response(
            200, content=json_body,
            headers={"content-type": "text/plain"},
            request=httpx.Request("GET", "https://example.com/data"),
        )
        with patch("apps.api.core.policy.socket.getaddrinfo", _mock_getaddrinfo_public), \
             patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await tool.execute({"url": "https://example.com/data"}, ctx)
        assert result.status == "success"
        assert result.output["type"] == "json"
        assert result.output["data"]["key"] == "value"

    def test_manifest(self, tool: FetchUrlTool) -> None:
        m = tool.manifest()
        assert m.name == "fetch_url"
        assert m.risk_level == RiskLevel.HIGH
        assert m.approval_required is True

    def test_retry_policy(self, tool: FetchUrlTool) -> None:
        rp = tool.retry_policy
        assert rp.max_retries == 1
        assert rp.idempotent is True
