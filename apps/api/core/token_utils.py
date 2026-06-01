"""Lightweight token estimation and cost accounting.

The ``estimate_tokens`` heuristic (~4 chars per token) is only used when a
provider's SDK response lacks real usage data.  Real token counts come from
``providers.base.TokenUsage`` on every ``LLMResponse``.

Pricing is loaded from ``pricing.json`` at the repo root on first access.
The file is data, not code — users can update prices without touching Python.
If the file is missing or malformed, a built-in fallback is used so the
system never crashes on a pricing problem.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.api.providers.base import TokenUsage

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Estimate token count using char/4 heuristic."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Context windows (unchanged — these are structural, not billing)
# ---------------------------------------------------------------------------

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-haiku-3.5-20241022": 200_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.5-pro": 1_000_000,
    "llama3.2": 8_192,
    "llama3.1": 128_000,
    "mistral": 8_192,
    "codellama": 16_384,
    "phi3": 4_096,
    "qwen2.5": 32_768,
}

DEFAULT_CONTEXT_WINDOW: int = 8_192


def get_context_window(model: str) -> int:
    """Return the context window size for a model.

    Tries exact match first, then prefix match.
    """
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]
    for key, value in MODEL_CONTEXT_WINDOWS.items():
        if model.startswith(key.rsplit("-", 1)[0]):
            return value
    return DEFAULT_CONTEXT_WINDOW


CONTEXT_RESERVE_PCT: float = 0.30


# ---------------------------------------------------------------------------
# Pricing — loaded from pricing.json, with hardcoded fallback
# ---------------------------------------------------------------------------

# Hardcoded fallback — used only when pricing.json is absent or broken.
_FALLBACK_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-3.5-20241022": {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "llama3.2": {"input": 0.0, "output": 0.0},
    "llama3.1": {"input": 0.0, "output": 0.0},
    "mistral": {"input": 0.0, "output": 0.0},
    "codellama": {"input": 0.0, "output": 0.0},
    "phi3": {"input": 0.0, "output": 0.0},
    "qwen2.5": {"input": 0.0, "output": 0.0},
}
_FALLBACK_LAST_VERIFIED: str = "2025-06-01"

DEFAULT_PRICING: dict[str, float] = {"input": 0.0, "output": 0.0}


def _find_pricing_json() -> Path | None:
    """Walk upward from this file to locate ``pricing.json`` at the repo root."""
    here = Path(__file__).resolve().parent
    for ancestor in [here] + list(here.parents):
        candidate = ancestor / "pricing.json"
        if candidate.is_file():
            return candidate
    return None


# Module-level cache — loaded once on first access.
_loaded: bool = False
MODEL_PRICING: dict[str, dict[str, float]] = {}
PRICING_LAST_VERIFIED: str = ""


def _ensure_loaded() -> None:
    """Load ``pricing.json`` on first call (lazy singleton)."""
    global _loaded, MODEL_PRICING, PRICING_LAST_VERIFIED
    if _loaded:
        return
    _loaded = True

    path = _find_pricing_json()
    if path is None:
        logger.warning("pricing.json not found — using built-in fallback")
        MODEL_PRICING = dict(_FALLBACK_PRICING)
        PRICING_LAST_VERIFIED = _FALLBACK_LAST_VERIFIED
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        models = data.get("models", {})
        if not isinstance(models, dict) or not models:
            raise ValueError("'models' key missing or empty")
        MODEL_PRICING = models
        PRICING_LAST_VERIFIED = data.get("last_verified", _FALLBACK_LAST_VERIFIED)
        logger.info(
            "Loaded pricing for %d models from %s (verified %s)",
            len(MODEL_PRICING), path, PRICING_LAST_VERIFIED,
        )
    except Exception as exc:
        logger.warning("Failed to load pricing.json (%s) — using fallback", exc)
        MODEL_PRICING = dict(_FALLBACK_PRICING)
        PRICING_LAST_VERIFIED = _FALLBACK_LAST_VERIFIED


def get_pricing(model: str) -> dict[str, float]:
    """Return the pricing entry for *model*.

    Tries exact match, then prefix match.  Returns ``DEFAULT_PRICING``
    for unknown models.
    """
    _ensure_loaded()
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    for key, value in MODEL_PRICING.items():
        if model.startswith(key.rsplit("-", 1)[0]):
            return value
    return DEFAULT_PRICING


def compute_cost(model: str, usage: "TokenUsage") -> float:
    """Compute estimated cost in USD for a single LLM call."""
    p = get_pricing(model)
    return (
        usage.input_tokens * p.get("input", 0.0)
        + usage.output_tokens * p.get("output", 0.0)
        + usage.cache_read_tokens * p.get("cache_read", 0.0)
        + usage.cache_write_tokens * p.get("cache_write", 0.0)
    ) / 1_000_000


def reload_pricing() -> None:
    """Force a re-read of ``pricing.json`` (e.g. after a hot-edit)."""
    global _loaded
    _loaded = False
    _ensure_loaded()
