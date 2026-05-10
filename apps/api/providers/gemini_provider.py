"""
providers/gemini_provider — Concrete ``LLMProvider`` for Google Gemini.

Wraps the official ``google-genai`` SDK (the unified successor to the legacy
``google-generativeai`` package). Translates the normalized provider
interface into ``client.aio.models.generate_content(...)`` calls, and the
SDK's response object back into ``LLMResponse``.

This file is the *only* place in the codebase that imports from
``google.genai``. Anything else that needs Gemini must go through the
``LLMProvider`` interface.

References
----------
* SDK:     https://github.com/googleapis/python-genai
* Migrate: https://ai.google.dev/gemini-api/docs/migrate
"""
from __future__ import annotations

import asyncio
import json
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


class GeminiProvider(LLMProvider):
    """Google Gemini provider using ``google-genai`` async client.

    Parameters
    ----------
    api_key : str
        Gemini Developer API key from https://aistudio.google.com/app/apikey.
    model : str
        Gemini model identifier (e.g. ``gemini-2.5-flash`` or
        ``gemini-2.5-pro``).
    """

    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ProviderConfigError(
                "GeminiProvider requires an API key. Set GEMINI_API_KEY in .env."
            )
        try:
            # ``google.genai`` is the new unified SDK. The legacy
            # ``google.generativeai`` package is deprecated and we do NOT use it.
            from google import genai
        except ImportError as exc:
            raise ProviderConfigError(
                "The 'google-genai' package is not installed. "
                "Run: pip install google-genai"
            ) from exc

        # Construct the client. The async surface is reached via ``.aio``.
        self._client = genai.Client(api_key=api_key)
        self._model = model

    # ------------------------------------------------------------------
    # Translation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_gemini_contents(messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """Translate normalized messages into Gemini's ``contents`` format.

        Gemini's roles are ``user`` and ``model`` (no ``system`` and no
        ``assistant``). System content is passed separately via the
        ``system_instruction`` config field. Assistant messages map to
        ``model``. Any stray system message in the array is dropped — the
        caller's ``system`` kwarg wins.
        """
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue
            role = "model" if m.role == "assistant" else "user"
            out.append({"role": role, "parts": [{"text": m.content}]})
        return out

    @staticmethod
    def _to_gemini_tools(tools: list[LLMToolSchema] | None) -> list[Any] | None:
        """Translate normalized tool schemas into Gemini's ``Tool`` shape.

        Gemini accepts ``types.Tool(function_declarations=[...])`` where each
        function declaration has ``name``, ``description``, and ``parameters``
        (a JSON Schema). We build the dict form, which the SDK accepts and
        coerces into the typed structure.
        """
        if not tools:
            return None
        try:
            from google.genai import types  # noqa: F401 (validate import)
        except ImportError:
            return None

        function_declarations = [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema or {"type": "object"},
            }
            for t in tools
        ]
        # SDK accepts a list of dicts that look like Tool(function_declarations=...).
        return [{"function_declarations": function_declarations}]

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
        return await self._generate_internal(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            json_mode=False,
        )

    async def generate_json(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Override using Gemini's native JSON mode for higher reliability.

        Sets ``response_mime_type='application/json'`` so Gemini constrains
        its output to syntactically valid JSON.
        """
        response = await self._generate_internal(
            messages=messages,
            system=system,
            tools=None,
            max_tokens=max_tokens,
            temperature=None,
            timeout=timeout,
            json_mode=True,
        )
        text = (response.text or "").strip()
        # Defence-in-depth: even with native JSON mode, strip fences if any.
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"Gemini returned invalid JSON: {exc}. First 200 chars: {text[:200]!r}"
            ) from exc

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _generate_internal(
        self,
        *,
        messages: list[LLMMessage],
        system: str | None,
        tools: list[LLMToolSchema] | None,
        max_tokens: int,
        temperature: float | None,
        timeout: float,
        json_mode: bool,
    ) -> LLMResponse:
        try:
            from google.genai import types
            from google.genai.errors import APIError
        except ImportError as exc:  # pragma: no cover
            raise ProviderConfigError("google-genai SDK missing") from exc

        if system is None:
            system = next((m.content for m in messages if m.role == "system"), None)

        contents = self._to_gemini_contents(messages)
        gem_tools = self._to_gemini_tools(tools)

        # Build the GenerateContentConfig. Only set fields we have values for —
        # the SDK defaults are sensible for everything else.
        config_kwargs: dict[str, Any] = {"max_output_tokens": max_tokens}
        if system is not None:
            config_kwargs["system_instruction"] = system
        if temperature is not None:
            config_kwargs["temperature"] = temperature
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        if gem_tools is not None:
            config_kwargs["tools"] = gem_tools
        config = types.GenerateContentConfig(**config_kwargs)

        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model, contents=contents, config=config
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise ProviderTimeoutError(
                f"Gemini API timed out after {timeout}s"
            ) from exc
        except APIError as exc:
            # The SDK exposes ``code`` (HTTP status) and ``message`` attributes.
            code = getattr(exc, "code", None)
            if code in (401, 403):
                raise ProviderAuthError(f"Gemini auth failed: {exc}") from exc
            if code == 429:
                raise ProviderRateLimitError(f"Gemini rate-limited: {exc}") from exc
            raise LLMProviderError(f"Gemini API error: {exc}") from exc

        # Translate the response. Gemini's ``response.text`` is a convenience
        # accessor that concatenates all text parts; we also walk parts to
        # collect any function calls.
        text = (getattr(response, "text", None) or "").strip()
        tool_calls: list[LLMToolCall] = []
        for fc in getattr(response, "function_calls", None) or []:
            tool_calls.append(
                LLMToolCall(
                    id=getattr(fc, "id", "") or getattr(fc, "name", ""),
                    name=getattr(fc, "name", ""),
                    arguments=dict(getattr(fc, "args", {}) or {}),
                )
            )

        finish_reason = None
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            fr = getattr(candidates[0], "finish_reason", None)
            finish_reason = str(fr) if fr is not None else None

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            raw=None,
        )
