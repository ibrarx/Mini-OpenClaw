"""
apps.api.providers — LLM provider abstraction layer.

This package decouples Mini-OpenClaw's agent logic from any single LLM vendor.
The agent calls a generic `LLMProvider` interface; concrete subclasses translate
that interface into vendor-specific SDK calls (Anthropic, Gemini, …).

Public surface:
    LLMProvider          — abstract base class every provider implements.
    LLMMessage           — normalized chat message (role + content).
    LLMToolSchema        — normalized tool definition (name + JSON schema).
    LLMResponse          — normalized response (text + optional tool_calls).
    LLMProviderError     — provider-agnostic exception hierarchy.
    build_provider()     — factory that returns a configured provider.
    ProviderType         — enum of supported provider IDs.
    AnthropicProvider    — concrete Anthropic Claude implementation.
    GeminiProvider       — concrete Google Gemini implementation.

Adding a new provider is a 3-step recipe — see ``docs/provider-abstraction.md``.
"""
from __future__ import annotations

from apps.api.providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMToolCall,
    LLMToolSchema,
)
from apps.api.providers.errors import (
    LLMProviderError,
    ProviderAuthError,
    ProviderConfigError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from apps.api.providers.factory import ProviderType, build_provider

# Concrete providers are imported lazily inside ``factory.build_provider`` so
# that the optional ``google-genai`` dependency is not required when only
# Anthropic is in use. Direct imports remain available for advanced callers.
__all__ = [
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "LLMToolCall",
    "LLMToolSchema",
    "LLMProviderError",
    "ProviderAuthError",
    "ProviderConfigError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderType",
    "build_provider",
]
