"""
Unit tests for the LLM provider abstraction layer.

Covers:
* Factory selection by ``LLM_PROVIDER`` (defaults, unknown values, missing keys)
* AnthropicProvider message translation, JSON-mode parsing, exception mapping
* GeminiProvider message translation, JSON-mode parsing, exception mapping
* Markdown-fence stripping in the base class ``generate_json``

All SDK calls are mocked — these tests never hit the network.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.config import Settings
from apps.api.providers.anthropic_provider import AnthropicProvider
from apps.api.providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
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
from apps.api.providers.gemini_provider import GeminiProvider


# ===========================================================================
# Factory tests
# ===========================================================================


class TestFactory:
    def test_default_is_anthropic(self) -> None:
        s = Settings(anthropic_api_key="k")
        p = build_provider(s)
        assert p.name == "anthropic"

    def test_explicit_anthropic(self) -> None:
        s = Settings(llm_provider="anthropic", anthropic_api_key="k")
        p = build_provider(s)
        assert p.name == "anthropic"
        assert p.model == s.anthropic_model

    def test_explicit_gemini(self) -> None:
        s = Settings(llm_provider="gemini", gemini_api_key="k")
        p = build_provider(s)
        assert p.name == "gemini"
        assert p.model == s.gemini_model

    def test_case_insensitive(self) -> None:
        s = Settings(llm_provider="GEMINI", gemini_api_key="k")
        p = build_provider(s)
        assert p.name == "gemini"

    def test_unknown_provider_raises(self) -> None:
        s = Settings(llm_provider="cohere", anthropic_api_key="k")
        with pytest.raises(ProviderConfigError) as exc_info:
            build_provider(s)
        assert "cohere" in str(exc_info.value).lower()

    def test_anthropic_missing_key_raises(self) -> None:
        s = Settings(llm_provider="anthropic", anthropic_api_key="")
        with pytest.raises(ProviderConfigError):
            build_provider(s)

    def test_gemini_missing_key_raises(self) -> None:
        s = Settings(llm_provider="gemini", gemini_api_key="")
        with pytest.raises(ProviderConfigError):
            build_provider(s)

    def test_provider_type_enum_values(self) -> None:
        """Whitelist of supported provider IDs is small and stable."""
        assert set(p.value for p in ProviderType) == {"anthropic", "gemini"}


# ===========================================================================
# AnthropicProvider
# ===========================================================================


def _ant_block(text: str | None = None, btype: str = "text") -> MagicMock:
    """Mimic an Anthropic content block."""
    b = MagicMock()
    b.type = btype
    if text is not None:
        b.text = text
    return b


def _ant_response(text: str, stop_reason: str = "end_turn") -> MagicMock:
    """Mimic the Anthropic SDK's Message response."""
    r = MagicMock()
    r.content = [_ant_block(text=text)]
    r.stop_reason = stop_reason
    return r


class TestAnthropicProvider:
    def test_missing_key_raises(self) -> None:
        with pytest.raises(ProviderConfigError):
            AnthropicProvider(api_key="", model="claude-x")

    def test_message_translation_strips_system_from_array(self) -> None:
        msgs = [
            LLMMessage(role="system", content="stay neutral"),
            LLMMessage(role="user", content="hello"),
            LLMMessage(role="assistant", content="hi"),
        ]
        out = AnthropicProvider._to_anthropic_messages(msgs)
        # system message must NOT appear in Anthropic's messages array
        assert all(m["role"] != "system" for m in out)
        assert out == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

    def test_tool_translation(self) -> None:
        tools = [
            LLMToolSchema(
                name="list_files",
                description="List files",
                input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            )
        ]
        out = AnthropicProvider._to_anthropic_tools(tools)
        assert out == [
            {
                "name": "list_files",
                "description": "List files",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            }
        ]

    def test_tool_translation_empty(self) -> None:
        assert AnthropicProvider._to_anthropic_tools(None) is None
        assert AnthropicProvider._to_anthropic_tools([]) is None

    @pytest.mark.asyncio
    async def test_generate_happy_path(self) -> None:
        p = AnthropicProvider(api_key="test", model="claude-x")
        p._client = MagicMock()
        p._client.messages.create = AsyncMock(return_value=_ant_response("hello world"))

        resp = await p.generate(
            messages=[LLMMessage(role="user", content="hi")],
            system="be brief",
        )

        assert resp.text == "hello world"
        assert resp.finish_reason == "end_turn"
        # Confirm the SDK got the right args.
        call = p._client.messages.create.call_args
        assert call.kwargs["model"] == "claude-x"
        assert call.kwargs["system"] == "be brief"
        assert call.kwargs["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_generate_with_system_fallback_from_messages(self) -> None:
        """If no ``system`` kwarg, the first system-role message is hoisted."""
        p = AnthropicProvider(api_key="test", model="claude-x")
        p._client = MagicMock()
        p._client.messages.create = AsyncMock(return_value=_ant_response("ok"))

        await p.generate(
            messages=[
                LLMMessage(role="system", content="hoisted"),
                LLMMessage(role="user", content="hi"),
            ]
        )
        assert p._client.messages.create.call_args.kwargs["system"] == "hoisted"

    @pytest.mark.asyncio
    async def test_generate_tool_use_extracted(self) -> None:
        p = AnthropicProvider(api_key="test", model="claude-x")
        # Build a response with a tool_use block.
        tu = MagicMock()
        tu.type = "tool_use"
        tu.id = "toolu_1"
        tu.name = "list_files"
        tu.input = {"path": "."}
        resp = MagicMock()
        resp.content = [tu, _ant_block("done")]
        resp.stop_reason = "tool_use"
        p._client = MagicMock()
        p._client.messages.create = AsyncMock(return_value=resp)

        out = await p.generate(messages=[LLMMessage(role="user", content="ls")])
        assert out.text == "done"
        assert len(out.tool_calls) == 1
        assert out.tool_calls[0].name == "list_files"
        assert out.tool_calls[0].arguments == {"path": "."}

    @pytest.mark.asyncio
    async def test_generate_timeout_mapped(self) -> None:
        p = AnthropicProvider(api_key="test", model="claude-x")
        p._client = MagicMock()
        p._client.messages.create = AsyncMock(side_effect=asyncio.TimeoutError())
        with pytest.raises(ProviderTimeoutError):
            await p.generate(messages=[LLMMessage(role="user", content="hi")], timeout=0.01)

    @pytest.mark.asyncio
    async def test_generate_auth_error_mapped(self) -> None:
        from anthropic import AuthenticationError

        p = AnthropicProvider(api_key="test", model="claude-x")
        p._client = MagicMock()
        # AuthenticationError(message, response, body) — construct via MagicMock side_effect
        exc = AuthenticationError(
            message="unauthorized",
            response=MagicMock(status_code=401, headers={}),
            body=None,
        )
        p._client.messages.create = AsyncMock(side_effect=exc)
        with pytest.raises(ProviderAuthError):
            await p.generate(messages=[LLMMessage(role="user", content="hi")])

    @pytest.mark.asyncio
    async def test_generate_rate_limit_mapped(self) -> None:
        from anthropic import RateLimitError

        p = AnthropicProvider(api_key="test", model="claude-x")
        p._client = MagicMock()
        exc = RateLimitError(
            message="too many",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        p._client.messages.create = AsyncMock(side_effect=exc)
        with pytest.raises(ProviderRateLimitError):
            await p.generate(messages=[LLMMessage(role="user", content="hi")])

    @pytest.mark.asyncio
    async def test_generate_json_strips_markdown_fences(self) -> None:
        p = AnthropicProvider(api_key="test", model="claude-x")
        p._client = MagicMock()
        payload = {"task_type": "direct_answer", "steps": []}
        wrapped = f"```json\n{json.dumps(payload)}\n```"
        p._client.messages.create = AsyncMock(return_value=_ant_response(wrapped))

        out = await p.generate_json(messages=[LLMMessage(role="user", content="x")])
        assert out == payload

    @pytest.mark.asyncio
    async def test_generate_json_invalid_raises(self) -> None:
        p = AnthropicProvider(api_key="test", model="claude-x")
        p._client = MagicMock()
        p._client.messages.create = AsyncMock(return_value=_ant_response("not json"))
        with pytest.raises(LLMProviderError):
            await p.generate_json(messages=[LLMMessage(role="user", content="x")])


# ===========================================================================
# GeminiProvider
# ===========================================================================


def _gem_response(text: str, finish: str = "STOP") -> MagicMock:
    """Mimic the google-genai SDK's GenerateContentResponse."""
    r = MagicMock()
    r.text = text
    r.function_calls = []
    cand = MagicMock()
    cand.finish_reason = finish
    r.candidates = [cand]
    return r


class TestGeminiProvider:
    def test_missing_key_raises(self) -> None:
        with pytest.raises(ProviderConfigError):
            GeminiProvider(api_key="", model="gemini-2.5-flash")

    def test_message_translation_strips_system(self) -> None:
        msgs = [
            LLMMessage(role="system", content="be calm"),
            LLMMessage(role="user", content="hello"),
            LLMMessage(role="assistant", content="hi"),
        ]
        out = GeminiProvider._to_gemini_contents(msgs)
        # system stripped; assistant mapped to 'model'
        assert all(c["role"] != "system" for c in out)
        assert out == [
            {"role": "user", "parts": [{"text": "hello"}]},
            {"role": "model", "parts": [{"text": "hi"}]},
        ]

    def test_tool_translation(self) -> None:
        tools = [
            LLMToolSchema(
                name="list_files",
                description="List files",
                input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            )
        ]
        out = GeminiProvider._to_gemini_tools(tools)
        assert out is not None
        assert len(out) == 1
        decls = out[0]["function_declarations"]
        assert decls[0]["name"] == "list_files"
        assert decls[0]["description"] == "List files"
        assert decls[0]["parameters"]["properties"]["path"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_generate_happy_path(self) -> None:
        p = GeminiProvider(api_key="test", model="gemini-2.5-flash")
        # Replace the async surface with mocks.
        p._client = MagicMock()
        p._client.aio.models.generate_content = AsyncMock(
            return_value=_gem_response("hello from gemini")
        )

        resp = await p.generate(
            messages=[LLMMessage(role="user", content="hi")],
            system="be brief",
        )

        assert resp.text == "hello from gemini"
        # Inspect config passed to the SDK.
        call_kwargs = p._client.aio.models.generate_content.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.5-flash"
        # system_instruction is inside the config object
        config = call_kwargs["config"]
        assert config.system_instruction == "be brief"
        assert config.max_output_tokens == 2048
        # JSON mode NOT set for plain generate()
        assert getattr(config, "response_mime_type", None) is None

    @pytest.mark.asyncio
    async def test_generate_json_sets_native_json_mode(self) -> None:
        p = GeminiProvider(api_key="test", model="gemini-2.5-flash")
        payload = {"task_type": "direct_answer", "steps": []}
        p._client = MagicMock()
        p._client.aio.models.generate_content = AsyncMock(
            return_value=_gem_response(json.dumps(payload))
        )

        out = await p.generate_json(messages=[LLMMessage(role="user", content="x")])
        assert out == payload
        # Verify response_mime_type was set.
        config = p._client.aio.models.generate_content.call_args.kwargs["config"]
        assert config.response_mime_type == "application/json"

    @pytest.mark.asyncio
    async def test_generate_json_strips_fences_even_in_json_mode(self) -> None:
        """Defence-in-depth: even if Gemini wraps in fences, we strip them."""
        p = GeminiProvider(api_key="test", model="gemini-2.5-flash")
        payload = {"ok": True}
        wrapped = f"```json\n{json.dumps(payload)}\n```"
        p._client = MagicMock()
        p._client.aio.models.generate_content = AsyncMock(
            return_value=_gem_response(wrapped)
        )
        out = await p.generate_json(messages=[LLMMessage(role="user", content="x")])
        assert out == payload

    @pytest.mark.asyncio
    async def test_generate_json_invalid_raises(self) -> None:
        p = GeminiProvider(api_key="test", model="gemini-2.5-flash")
        p._client = MagicMock()
        p._client.aio.models.generate_content = AsyncMock(
            return_value=_gem_response("not json")
        )
        with pytest.raises(LLMProviderError):
            await p.generate_json(messages=[LLMMessage(role="user", content="x")])

    @pytest.mark.asyncio
    async def test_generate_timeout_mapped(self) -> None:
        p = GeminiProvider(api_key="test", model="gemini-2.5-flash")
        p._client = MagicMock()
        p._client.aio.models.generate_content = AsyncMock(side_effect=asyncio.TimeoutError())
        with pytest.raises(ProviderTimeoutError):
            await p.generate(
                messages=[LLMMessage(role="user", content="hi")], timeout=0.01
            )

    @pytest.mark.asyncio
    async def test_generate_api_error_mapped_by_code(self) -> None:
        """401/403 → auth, 429 → rate limit, else → generic."""
        from google.genai import errors as gerrors

        p = GeminiProvider(api_key="test", model="gemini-2.5-flash")
        p._client = MagicMock()

        # Build a synthetic APIError with a code attribute.
        def _mk_err(code: int) -> Exception:
            err = MagicMock(spec=gerrors.APIError)
            # We can't easily construct a real APIError without a response; use
            # patching to ensure isinstance() check sees our exception type.
            err.code = code
            return err

        # Patch the APIError import inside the provider so isinstance(...) works
        # for our MagicMock exceptions. Easier: raise real-looking subclasses.
        class FakeAPIError(gerrors.APIError):
            def __init__(self, code: int, message: str = "x") -> None:
                self.code = code
                self.message = message

            def __str__(self) -> str:
                return f"[{self.code}] {self.message}"

        # 401 → ProviderAuthError
        p._client.aio.models.generate_content = AsyncMock(side_effect=FakeAPIError(401))
        with pytest.raises(ProviderAuthError):
            await p.generate(messages=[LLMMessage(role="user", content="hi")])

        # 429 → ProviderRateLimitError
        p._client.aio.models.generate_content = AsyncMock(side_effect=FakeAPIError(429))
        with pytest.raises(ProviderRateLimitError):
            await p.generate(messages=[LLMMessage(role="user", content="hi")])

        # 500 → generic LLMProviderError
        p._client.aio.models.generate_content = AsyncMock(side_effect=FakeAPIError(500))
        with pytest.raises(LLMProviderError):
            await p.generate(messages=[LLMMessage(role="user", content="hi")])

    @pytest.mark.asyncio
    async def test_function_calls_extracted(self) -> None:
        p = GeminiProvider(api_key="test", model="gemini-2.5-flash")
        fc = MagicMock()
        fc.id = "fc_1"
        fc.name = "list_files"
        fc.args = {"path": "."}
        r = _gem_response("")
        r.function_calls = [fc]
        p._client = MagicMock()
        p._client.aio.models.generate_content = AsyncMock(return_value=r)

        out = await p.generate(messages=[LLMMessage(role="user", content="ls")])
        assert len(out.tool_calls) == 1
        assert out.tool_calls[0].name == "list_files"
        assert out.tool_calls[0].arguments == {"path": "."}


# ===========================================================================
# Base-class behaviour (independent of any specific SDK)
# ===========================================================================


class _StubProvider(LLMProvider):
    """Minimal concrete provider for testing the base class's default methods."""

    name = "stub"

    def __init__(self, text: str = "") -> None:
        self._text = text
        self._model = "stub-1"

    async def generate(self, messages, *, system=None, tools=None,
                       max_tokens=2048, temperature=None, timeout=60.0):
        return LLMResponse(text=self._text)


class TestBaseProvider:
    @pytest.mark.asyncio
    async def test_generate_json_default_parses_plain_json(self) -> None:
        p = _StubProvider(text=json.dumps({"a": 1}))
        out = await p.generate_json(messages=[LLMMessage(role="user", content="x")])
        assert out == {"a": 1}

    @pytest.mark.asyncio
    async def test_generate_json_default_strips_fences(self) -> None:
        p = _StubProvider(text='```json\n{"a": 2}\n```')
        out = await p.generate_json(messages=[LLMMessage(role="user", content="x")])
        assert out == {"a": 2}

    @pytest.mark.asyncio
    async def test_generate_json_default_strips_bare_fences(self) -> None:
        p = _StubProvider(text='```\n{"a": 3}\n```')
        out = await p.generate_json(messages=[LLMMessage(role="user", content="x")])
        assert out == {"a": 3}

    @pytest.mark.asyncio
    async def test_generate_json_default_raises_on_invalid(self) -> None:
        p = _StubProvider(text="hello, not json")
        with pytest.raises(LLMProviderError):
            await p.generate_json(messages=[LLMMessage(role="user", content="x")])

    def test_model_property_default(self) -> None:
        p = _StubProvider()
        assert p.model == "stub-1"
