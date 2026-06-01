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

    Supports two modes:

    1. **AI Studio** (default): uses an API key from
       https://aistudio.google.com/app/apikey. Routes through
       ``generativelanguage.googleapis.com``.

    2. **Vertex AI**: uses GCP Application Default Credentials. Routes
       through ``{location}-aiplatform.googleapis.com``. Required for
       GCP billing / credits. Set ``vertex_ai=True`` and provide
       ``gcp_project`` and ``gcp_location``.

    Parameters
    ----------
    api_key : str
        Gemini Developer API key (AI Studio mode). Ignored when
        ``vertex_ai=True``.
    model : str
        Gemini model identifier (e.g. ``gemini-2.5-flash``).
    vertex_ai : bool
        If ``True``, use Vertex AI endpoint instead of AI Studio.
    gcp_project : str
        GCP project ID (required when ``vertex_ai=True``).
    gcp_location : str
        GCP region (default ``us-central1``).
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        vertex_ai: bool = False,
        gcp_project: str = "",
        gcp_location: str = "us-central1",
    ) -> None:
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderConfigError(
                "The 'google-genai' package is not installed. "
                "Run: pip install google-genai"
            ) from exc

        if vertex_ai:
            # Vertex AI mode — uses Application Default Credentials.
            # User must run: gcloud auth application-default login
            if not gcp_project:
                raise ProviderConfigError(
                    "Vertex AI mode requires GCP_PROJECT in .env. "
                    "Also run: gcloud auth application-default login"
                )
            self._client = genai.Client(
                vertexai=True,
                project=gcp_project,
                location=gcp_location,
            )
            logger.info(
                "Gemini: Vertex AI mode (project=%s, location=%s)",
                gcp_project, gcp_location,
            )
        else:
            # AI Studio mode — uses API key.
            if not api_key:
                raise ProviderConfigError(
                    "GeminiProvider requires an API key. Set GEMINI_API_KEY in .env, "
                    "or set VERTEX_AI=true with GCP_PROJECT for Vertex AI mode."
                )
            self._client = genai.Client(api_key=api_key)
            logger.info("Gemini: AI Studio mode (api_key)")

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
        except json.JSONDecodeError:
            pass
        # Repair: Gemini often fails to escape newlines inside JSON strings.
        # Replace literal control characters with spaces and retry.
        repaired = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        try:
            return json.loads(repaired.strip())
        except json.JSONDecodeError:
            pass
        # Fallback: extract first balanced { … } block.
        parsed = self._extract_json_object(text.strip())
        if parsed is not None:
            return parsed
        # Last resort: try balanced extraction on repaired text too.
        parsed = self._extract_json_object(repaired.strip())
        if parsed is not None:
            return parsed
        raise LLMProviderError(
            f"Gemini returned invalid JSON. First 200 chars: {text[:200]!r}"
        )

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any] | None:
        """Find the first balanced top-level JSON object in *text*."""
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

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
