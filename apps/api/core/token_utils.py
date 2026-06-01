"""Lightweight token estimation and cost accounting.

The ``estimate_tokens`` heuristic (~4 chars per token) is only used when a
provider's SDK response lacks real usage data.  Real token counts come from
``providers.base.TokenUsage`` on every ``LLMResponse``.

The pricing table is maintained manually. Prices change — we record a
``PRICING_LAST_VERIFIED`` date and show it in the UI next to dollar figures
so the project never overstates the accuracy of cost estimates.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.api.providers.base import TokenUsage


def estimate_tokens(text: str) -> int:
    """Estimate token count using char/4 heuristic."""
    return max(1, len(text) // 4)


# Context window sizes by model family
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-20250514": 200_000,  # deprecated, kept for existing runs
    "claude-haiku-3.5-20241022": 200_000,
    # Gemini
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.5-pro": 1_000_000,
    # Ollama / local models (conservative defaults)
    "llama3.2": 8_192,
    "llama3.1": 128_000,
    "mistral": 8_192,
    "codellama": 16_384,
    "phi3": 4_096,
    "qwen2.5": 32_768,
}

DEFAULT_CONTEXT_WINDOW: int = 8_192  # Conservative default for unknown models


def get_context_window(model: str) -> int:
    """Return the context window size for a model.

    Tries exact match first, then prefix match (e.g. "claude-sonnet-4"
    matches "claude-sonnet-4-6").
    """
    # Exact match first
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]
    # Prefix match (e.g., "claude-sonnet-4" matches "claude-sonnet-4-6")
    for key, value in MODEL_CONTEXT_WINDOWS.items():
        if model.startswith(key.rsplit("-", 1)[0]):
            return value
    return DEFAULT_CONTEXT_WINDOW


# Reserve 30% of context for the LLM's response + system prompt overhead
CONTEXT_RESERVE_PCT: float = 0.30


# ---------------------------------------------------------------------------
# Pricing — USD per 1,000,000 tokens
# ---------------------------------------------------------------------------

# IMPORTANT: prices change. Verify against the provider's pricing page before
# each release. The UI shows PRICING_LAST_VERIFIED alongside any dollar amount.
PRICING_LAST_VERIFIED: str = "2025-06-01"

MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic — https://www.anthropic.com/pricing
    "claude-sonnet-4-20250514": {
        "input": 3.00, "output": 15.00,
        "cache_read": 0.30, "cache_write": 3.75,
    },
    "claude-sonnet-4-6": {
        "input": 3.00, "output": 15.00,
        "cache_read": 0.30, "cache_write": 3.75,
    },
    "claude-haiku-3.5-20241022": {
        "input": 0.80, "output": 4.00,
        "cache_read": 0.08, "cache_write": 1.00,
    },
    # Gemini — https://ai.google.dev/pricing
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro":   {"input": 1.25, "output": 10.00},
    # Local models — free but tokens are still real
    "llama3.2":   {"input": 0.0, "output": 0.0},
    "llama3.1":   {"input": 0.0, "output": 0.0},
    "mistral":    {"input": 0.0, "output": 0.0},
    "codellama":  {"input": 0.0, "output": 0.0},
    "phi3":       {"input": 0.0, "output": 0.0},
    "qwen2.5":    {"input": 0.0, "output": 0.0},
}

DEFAULT_PRICING: dict[str, float] = {"input": 0.0, "output": 0.0}


def get_pricing(model: str) -> dict[str, float]:
    """Return the pricing entry for *model*.

    Tries exact match first, then prefix match (same logic as
    ``get_context_window``).  Returns ``DEFAULT_PRICING`` for unknown
    models — the UI should flag these as "$0.00 (unknown model)".
    """
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    for key, value in MODEL_PRICING.items():
        if model.startswith(key.rsplit("-", 1)[0]):
            return value
    return DEFAULT_PRICING


def compute_cost(model: str, usage: "TokenUsage") -> float:
    """Compute estimated cost in USD for a single LLM call.

    Uses the centralized pricing table. Returns 0.0 for unknown models
    or local models (but tokens are still tracked).
    """
    p = get_pricing(model)
    return (
        usage.input_tokens * p.get("input", 0.0)
        + usage.output_tokens * p.get("output", 0.0)
        + usage.cache_read_tokens * p.get("cache_read", 0.0)
        + usage.cache_write_tokens * p.get("cache_write", 0.0)
    ) / 1_000_000
