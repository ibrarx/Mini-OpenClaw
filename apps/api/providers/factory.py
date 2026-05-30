"""
providers/factory — Build a configured ``LLMProvider`` from ``Settings``.

The factory is the only place where the application chooses *which*
concrete provider to instantiate. Adding a new provider means:

1. Implement ``LLMProvider`` in a new file under ``providers/``.
2. Add an entry to ``ProviderType``.
3. Add a branch in ``build_provider``.
4. Add the relevant ``<vendor>_api_key`` and ``<vendor>_model`` fields to
   ``apps.api.config.Settings``.
5. Document the new ``LLM_PROVIDER`` value in ``.env.example`` and README.

Nothing else in the codebase needs to change.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

from apps.api.providers.errors import ProviderConfigError

if TYPE_CHECKING:
    from apps.api.config import Settings
    from apps.api.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class ProviderType(str, Enum):
    """Enum of supported provider identifiers.

    Values must match the lowercase string set in the ``LLM_PROVIDER`` env
    var. New providers add a member here and a branch in ``build_provider``.
    """

    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"


def build_provider(settings: "Settings") -> "LLMProvider":
    """Construct and return the provider selected by ``settings.llm_provider``.

    The function performs all configuration validation up front — if it
    returns successfully, the resulting provider is guaranteed to have a
    non-empty API key and a model identifier.

    Raises
    ------
    ProviderConfigError
        If the provider name is unknown, or the required API key is missing.
    """
    raw = (settings.llm_provider or "").strip().lower()
    if not raw:
        # Sensible default — preserves zero-config behaviour for users who
        # only configured ANTHROPIC_API_KEY (the pre-refactor state).
        raw = ProviderType.ANTHROPIC.value

    try:
        ptype = ProviderType(raw)
    except ValueError as exc:
        allowed = ", ".join(p.value for p in ProviderType)
        raise ProviderConfigError(
            f"Unknown LLM_PROVIDER={raw!r}. Allowed: {allowed}."
        ) from exc

    if ptype is ProviderType.ANTHROPIC:
        # Lazy import keeps optional providers' deps off the critical path.
        from apps.api.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
        logger.info("LLM provider: anthropic (%s)", settings.anthropic_model)
        return provider

    if ptype is ProviderType.GEMINI:
        from apps.api.providers.gemini_provider import GeminiProvider

        provider = GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            vertex_ai=settings.vertex_ai,
            gcp_project=settings.gcp_project,
            gcp_location=settings.gcp_location,
        )
        mode = "vertex-ai" if settings.vertex_ai else "ai-studio"
        logger.info("LLM provider: gemini/%s (%s)", mode, settings.gemini_model)
        return provider

    if ptype is ProviderType.OLLAMA:
        from apps.api.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
        )
        logger.info("LLM provider: ollama (%s at %s)", settings.ollama_model, settings.ollama_base_url)
        return provider

    # Defensive — should be unreachable thanks to the Enum check above.
    raise ProviderConfigError(f"Unhandled provider type: {ptype}")  # pragma: no cover
