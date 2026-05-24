"""Lightweight token estimation without requiring tiktoken.

Uses a simple heuristic: ~4 characters per token for English text.
Good enough for budget management — we're not billing, just preventing overflow.
"""


def estimate_tokens(text: str) -> int:
    """Estimate token count using char/4 heuristic."""
    return max(1, len(text) // 4)


# Context window sizes by model family
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic
    "claude-sonnet-4-20250514": 200_000,
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
    matches "claude-sonnet-4-20250514").
    """
    # Exact match first
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]
    # Prefix match (e.g., "claude-sonnet-4" matches "claude-sonnet-4-20250514")
    for key, value in MODEL_CONTEXT_WINDOWS.items():
        if model.startswith(key.rsplit("-", 1)[0]):
            return value
    return DEFAULT_CONTEXT_WINDOW


# Reserve 30% of context for the LLM's response + system prompt overhead
CONTEXT_RESERVE_PCT: float = 0.30
