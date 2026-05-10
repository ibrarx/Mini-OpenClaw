"""
providers/errors — Provider-agnostic exception hierarchy.

The goal of this module is to keep upstream code (planner, orchestrator,
routes) free of vendor-specific exception types. Each concrete provider
translates its SDK's exceptions into one of these classes before re-raising.
"""
from __future__ import annotations


class LLMProviderError(Exception):
    """Base class for all provider-layer errors.

    Catch this in upstream code when you want to handle any provider failure
    uniformly (e.g. surface a "Planning failed: …" message to the user).
    """


class ProviderConfigError(LLMProviderError):
    """The provider is misconfigured — missing API key, unknown provider name,
    optional SDK not installed, etc. Usually a user-action problem (.env)."""


class ProviderAuthError(LLMProviderError):
    """The provider's API rejected the credentials. Often a wrong/expired key."""


class ProviderRateLimitError(LLMProviderError):
    """The provider's API returned a rate-limit/quota error. Caller may retry
    after a back-off."""


class ProviderTimeoutError(LLMProviderError):
    """The provider call exceeded the configured timeout. Usually network or
    overloaded upstream."""
