"""
providers/ollama_provider — Concrete ``LLMProvider`` for local Ollama models.

Wraps Ollama's OpenAI-compatible ``/v1/chat/completions`` endpoint using
``httpx.AsyncClient``. No API key is required — Ollama runs locally.

This file is the *only* place in the codebase that talks to Ollama's HTTP
API. Anything else that needs Ollama must go through the ``LLMProvider``
interface.

Recommended models
------------------
* ``llama3.2``  — best balance of speed and quality for agent tasks
* ``mistral``   — fast, good at following JSON instructions
* ``codellama`` — best for code-heavy workspaces
* ``phi3``      — smallest, runs on 8 GB RAM machines

References
----------
* Ollama:        https://ollama.ai
* OpenAI compat: https://github.com/ollama/ollama/blob/main/docs/openai.md
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
    LLMToolSchema,
)
from apps.api.providers.errors import (
    LLMProviderError,
    ProviderConfigError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)

# Ollama can be slow on first call (loading model into VRAM), so we use a
# generous default timeout.
_DEFAULT_TIMEOUT: float = 120.0


class OllamaProvider(LLMProvider):
    """Local Ollama provider using the OpenAI-compatible chat endpoint.

    Parameters
    ----------
    base_url : str
        Ollama server URL (default ``http://localhost:11434``).
    model : str
        Model identifier (e.g. ``llama3.2``, ``mistral``, ``codellama``).
    """

    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.2") -> None:
        try:
            import httpx  # noqa: F401
        except ImportError as exc:
            raise ProviderConfigError(
                "The 'httpx' package is not installed. "
                "Run: pip install httpx"
            ) from exc

        self._base_url = base_url.rstrip("/")
        self._model = model
        self._endpoint = f"{self._base_url}/v1/chat/completions"

    # ------------------------------------------------------------------
    # Translation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_messages(
        messages: list[LLMMessage],
        system: str | None = None,
    ) -> list[dict[str, str]]:
        """Translate normalized messages into OpenAI-compatible format.

        Unlike Anthropic (which uses a separate ``system`` parameter),
        Ollama's OpenAI-compatible endpoint includes system messages directly
        in the messages array.
        """
        out: list[dict[str, str]] = []

        # If an explicit system prompt is provided, prepend it.
        if system is not None:
            out.append({"role": "system", "content": system})

        for m in messages:
            # Skip system messages from the array if we already have an
            # explicit system prompt, to avoid duplication.
            if m.role == "system" and system is not None:
                continue
            out.append({"role": m.role, "content": m.content})

        return out

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
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> LLMResponse:
        return await self._call_ollama(
            messages=messages,
            system=system,
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
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """Override using Ollama's native JSON mode for higher reliability.

        Sets ``"format": "json"`` in the request body so Ollama constrains
        its output to syntactically valid JSON. The base class fallback
        (brace-scanning) is kept as a safety net.
        """
        response = await self._call_ollama(
            messages=messages,
            system=system,
            max_tokens=max_tokens,
            temperature=None,
            timeout=timeout,
            json_mode=True,
        )
        text = (response.text or "").strip()

        # Defence-in-depth: strip markdown fences if the model wrapped output.
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # Fast path: direct parse.
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fallback: use the base class brace-scanner to extract JSON from
        # preamble text (common with local models).
        try:
            return await super().generate_json(
                messages=messages,
                system=system,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        except LLMProviderError:
            pass

        raise LLMProviderError(
            f"Ollama returned invalid JSON. First 200 chars: {text[:200]!r}"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _call_ollama(
        self,
        *,
        messages: list[LLMMessage],
        system: str | None,
        max_tokens: int,
        temperature: float | None,
        timeout: float,
        json_mode: bool,
    ) -> LLMResponse:
        """Make an HTTP POST to Ollama's OpenAI-compatible endpoint."""
        import httpx

        # If no explicit system kwarg, extract from messages.
        if system is None:
            system = next((m.content for m in messages if m.role == "system"), None)

        chat_messages = self._build_messages(messages, system)

        body: dict[str, Any] = {
            "model": self._model,
            "messages": chat_messages,
            "stream": False,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            body["temperature"] = temperature
        else:
            body["temperature"] = 0.7
        if json_mode:
            body["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(self._endpoint, json=body)
        except httpx.ConnectError as exc:
            raise ProviderConfigError(
                f"Cannot connect to Ollama at {self._base_url}. "
                f"Is Ollama running? Start it with: ollama serve"
            ) from exc
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            raise ProviderTimeoutError(
                f"Ollama timed out after {timeout}s. The model may still be "
                f"loading into memory. Try again in a moment, or use a "
                f"smaller model."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Ollama HTTP error: {exc}") from exc

        # Handle error responses.
        if resp.status_code == 404:
            raise ProviderConfigError(
                f"Model '{self._model}' not found. "
                f"Pull it with: ollama pull {self._model}"
            )
        if resp.status_code >= 400:
            detail = resp.text[:300] if resp.text else f"HTTP {resp.status_code}"
            raise LLMProviderError(f"Ollama API error ({resp.status_code}): {detail}")

        data = resp.json()

        # Extract the response text from the OpenAI-compatible format.
        choices = data.get("choices", [])
        text = ""
        finish_reason = None
        if choices:
            message = choices[0].get("message", {})
            text = (message.get("content") or "").strip()
            finish_reason = choices[0].get("finish_reason")

        return LLMResponse(
            text=text,
            tool_calls=[],
            finish_reason=finish_reason,
            raw=data,
        )
