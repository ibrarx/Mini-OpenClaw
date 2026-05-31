"""
providers/anthropic_provider — Concrete ``LLMProvider`` for Anthropic Claude.

Wraps the official ``anthropic`` Python SDK (``AsyncAnthropic``). Translates
normalized ``LLMMessage`` / ``LLMToolSchema`` inputs into the
``client.messages.create(...)`` call, and the SDK's ``Message`` response into
a normalized ``LLMResponse``. Maps SDK exceptions onto the provider-agnostic
``providers.errors.*`` hierarchy.

This file is the *only* place in the codebase that imports from
``anthropic``. Anything else that needs Claude must go through the
``LLMProvider`` interface.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

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

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider using ``AsyncAnthropic``.

    Parameters
    ----------
    api_key : str
        Anthropic API key. Required and non-empty.
    model : str
        Claude model identifier (e.g. ``claude-sonnet-4-6``).
    """

    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ProviderConfigError(
                "AnthropicProvider requires an API key. Set ANTHROPIC_API_KEY in .env."
            )
        # Import lazily so that environments without the optional ``anthropic``
        # SDK installed can still import the providers package (e.g. when only
        # Gemini is in use). In practice ``anthropic`` is always installed,
        # but defensive lazy-imports keep the package portable.
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - import-time guard
            raise ProviderConfigError(
                "The 'anthropic' package is not installed. "
                "Run: pip install anthropic"
            ) from exc

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    # ------------------------------------------------------------------
    # Translation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_anthropic_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """Translate normalized messages into Anthropic's ``messages`` shape.

        Anthropic does NOT accept ``role="system"`` in the messages array — it
        is passed as the top-level ``system`` parameter. Callers should pass
        any system content via the ``system`` kwarg on ``generate``; if a
        system message sneaks into the list anyway, we silently drop it
        (the caller's ``system`` kwarg wins).
        """
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                # Anthropic forbids system messages in the array.
                continue
            out.append({"role": m.role, "content": m.content})
        return out

    @staticmethod
    def _to_anthropic_tools(tools: list[LLMToolSchema] | None) -> list[dict[str, Any]] | None:
        """Translate normalized tool schemas into Anthropic's tool format."""
        if not tools:
            return None
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema or {"type": "object"},
            }
            for t in tools
        ]

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        tools: list[LLMToolSchema] | None = None,
        max_tokens: int = 2048,
        temperature: float | None = None,
        timeout: float = 60.0,
    ) -> LLMResponse:
        # Translate inbound types.
        ant_messages = self._to_anthropic_messages(messages)
        # If no explicit ``system`` was passed, fall back to any system message
        # in the array for convenience.
        if system is None:
            system = next((m.content for m in messages if m.role == "system"), None)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": ant_messages,
        }
        if system is not None:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        ant_tools = self._to_anthropic_tools(tools)
        if ant_tools is not None:
            kwargs["tools"] = ant_tools

        # Translate SDK exceptions into our provider-agnostic hierarchy.
        try:
            from anthropic import APIError, AuthenticationError, RateLimitError
        except ImportError as exc:  # pragma: no cover
            raise ProviderConfigError("anthropic SDK missing") from exc

        try:
            response = await asyncio.wait_for(
                self._client.messages.create(**kwargs), timeout=timeout
            )
        except asyncio.TimeoutError as exc:
            raise ProviderTimeoutError(
                f"Anthropic API timed out after {timeout}s"
            ) from exc
        except AuthenticationError as exc:
            raise ProviderAuthError(f"Anthropic auth failed: {exc}") from exc
        except RateLimitError as exc:
            raise ProviderRateLimitError(f"Anthropic rate-limited: {exc}") from exc
        except APIError as exc:
            raise LLMProviderError(f"Anthropic API error: {exc}") from exc

        # Translate the response.
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        for block in response.content or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif btype == "tool_use":
                tool_calls.append(
                    LLMToolCall(
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", ""),
                        arguments=getattr(block, "input", {}) or {},
                    )
                )

        return LLMResponse(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            finish_reason=getattr(response, "stop_reason", None),
            raw=None,  # Skip raw dump — content already captured above.
        )
