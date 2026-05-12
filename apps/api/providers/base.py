"""
providers/base — Abstract ``LLMProvider`` interface and normalized DTOs.

This is the contract that every concrete provider implements. Code outside
the ``providers/`` package interacts with LLMs exclusively through this
interface — never through ``anthropic`` or ``google.genai`` directly.

Design notes
------------
* **Vendor-neutral primitives.** We use plain Pydantic models with a minimal
  surface (``role`` ∈ {"system", "user", "assistant"}, opaque ``content``
  string). Each provider maps that to its native message format internally.

* **JSON-mode contract.** Mini-OpenClaw's planner asks the model to emit a
  JSON plan. Rather than depend on each vendor's native tool-calling API
  (which differs in shape), we standardize on ``generate_json(...)``: the
  provider is responsible for whatever steering (system prompt, response_format,
  response_mime_type, etc.) yields a clean JSON string. This keeps the
  surface uniform and works with future providers like Ollama / OpenAI / Groq.

* **Native tool-calling hook.** ``LLMToolSchema`` and ``LLMToolCall`` exist
  on the interface so a future planner pass can opt into per-provider native
  tool calling without re-engineering the contract. The current V1 planner
  does not use them yet, but the types are stable.

* **Streaming hook.** ``stream_text()`` exists as an extension point. The V1
  planner does not stream; concrete providers may implement it now or later.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Normalized data types
# ---------------------------------------------------------------------------


MessageRole = Literal["system", "user", "assistant"]


class LLMMessage(BaseModel):
    """A single chat message in the normalized format.

    Mini-OpenClaw uses a flat string ``content`` field. Multi-modal content
    (images, audio) is a future extension and intentionally out of scope.
    """

    role: MessageRole
    content: str


class LLMToolSchema(BaseModel):
    """Vendor-neutral tool/function definition.

    Mirrors the JSON Schema convention used by OpenAI and (with small
    differences) Anthropic and Gemini. Concrete providers translate this
    into their native tool-declaration format.
    """

    name: str
    description: str
    # The JSON Schema describing the tool's arguments — same shape as
    # ``ToolManifest.input_schema`` already used elsewhere in the codebase.
    input_schema: dict[str, Any] = Field(default_factory=dict)


class LLMToolCall(BaseModel):
    """A tool invocation requested by the model.

    Populated only when native tool calling is used. The current V1 planner
    relies on JSON-mode (the model emits a plan as JSON text) and does not
    inspect this field, but providers must still produce it correctly when
    a future caller asks for native tool calling.
    """

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Normalized response returned by every provider.

    Attributes
    ----------
    text : str
        The model's text output, with vendor-specific framing already stripped
        (no markdown fences, no role tags, no chunk wrappers).
    tool_calls : list[LLMToolCall]
        Empty unless the caller passed ``tools=`` AND the provider supports
        native tool calling AND the model chose to use one.
    finish_reason : str | None
        Best-effort normalized reason (e.g. "stop", "tool_use", "length").
    raw : dict | None
        Provider-specific raw response, for audit. Opaque to callers.
    """

    text: str = ""
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract LLM provider.

    Every concrete subclass MUST implement ``generate``. ``generate_json`` has
    a default implementation that wraps ``generate`` and post-processes the
    text into valid JSON; providers that support a native JSON mode (e.g.
    Gemini's ``response_mime_type="application/json"``) SHOULD override it
    for reliability.

    Lifecycle
    ---------
    Instances are constructed once at orchestrator startup and reused for the
    lifetime of the process. They MUST be safe to call concurrently from many
    asyncio tasks. (Both the Anthropic and Gemini SDKs are concurrency-safe.)
    """

    # Subclasses set this to a stable string ("anthropic", "gemini", …) so
    # that audit logs and the /health endpoint can identify the active backend.
    name: str = "abstract"

    @property
    def model(self) -> str:
        """Return the model identifier this provider is configured with."""
        return getattr(self, "_model", "unknown")

    # -- core completion ----------------------------------------------------

    @abstractmethod
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
        """Run a single completion and return the normalized response.

        Concrete providers MUST translate their SDK's exceptions into the
        provider-agnostic types defined in ``providers.errors`` (timeout →
        ``ProviderTimeoutError``, 429 → ``ProviderRateLimitError``, 401/403 →
        ``ProviderAuthError``, everything else → ``LLMProviderError``).
        """

    # -- JSON mode (used by the planner) ------------------------------------

    async def generate_json(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Run a completion and return a parsed JSON object.

        Default implementation: call ``generate``, strip any markdown fences,
        and ``json.loads`` the result. If the model prefixed the JSON with
        reasoning text (common with ReAct prompts), we extract the first
        ``{…}`` block.

        Raises
        ------
        LLMProviderError
            If the model's output cannot be parsed as JSON.
        """
        import json

        response = await self.generate(
            messages=messages,
            system=system,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        text = (response.text or "").strip()
        # Strip ```json ... ``` fences if the model wrapped its output.
        if text.startswith("```"):
            # Drop the first line (```json or ```)
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # Try parsing directly first (fast path).
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fallback: the model may have prefixed the JSON with reasoning text.
        # Find the first top-level { … } block by scanning for balanced braces.
        start = text.find("{")
        if start != -1:
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
                        candidate = text[start : i + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break

        from apps.api.providers.errors import LLMProviderError

        raise LLMProviderError(
            f"{self.name} returned invalid JSON: "
            f"Expecting value: line 1 column 1 (char 0). "
            f"First 200 chars: {text[:200]!r}"
        )

    # -- streaming (optional) -----------------------------------------------

    async def stream_text(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> AsyncIterator[str]:  # pragma: no cover - default not used by V1
        """Stream incremental text deltas from the model.

        Default implementation falls back to a single ``generate`` call,
        yielding the full text once. Providers with native streaming SHOULD
        override this. Reserved for future UI work; the V1 orchestrator does
        not call this method.
        """
        response = await self.generate(
            messages=messages, system=system, max_tokens=max_tokens, timeout=timeout
        )
        yield response.text
