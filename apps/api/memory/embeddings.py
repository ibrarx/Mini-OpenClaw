"""
memory/embeddings — Embedding provider for semantic memory search.

Uses sentence-transformers with 'all-MiniLM-L6-v2' (384-dim, CPU, free).
Falls back gracefully if sentence-transformers is not installed.
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# Lazy flag — set on first attempt to load the model.
_SENTENCE_TRANSFORMERS_AVAILABLE: bool | None = None
_MODEL_CACHE: dict[str, Any] = {}


def _check_availability() -> bool:
    """Check if sentence-transformers is importable."""
    global _SENTENCE_TRANSFORMERS_AVAILABLE
    if _SENTENCE_TRANSFORMERS_AVAILABLE is not None:
        return _SENTENCE_TRANSFORMERS_AVAILABLE
    try:
        import sentence_transformers  # noqa: F401
        _SENTENCE_TRANSFORMERS_AVAILABLE = True
    except ImportError:
        _SENTENCE_TRANSFORMERS_AVAILABLE = False
        logger.warning(
            "sentence-transformers not installed. "
            "Memory search will fall back to keyword-only mode. "
            "Install with: pip install sentence-transformers"
        )
    return _SENTENCE_TRANSFORMERS_AVAILABLE


class EmbeddingProvider:
    """Provider-agnostic embedding interface.

    Loads a local sentence-transformers model (no API key needed).
    If the library is missing, all methods return None/empty gracefully
    so callers can fall back to keyword search.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model: Any = None
        self._available = _check_availability()
        self._dimension: int = 384  # default for all-MiniLM-L6-v2

    @property
    def available(self) -> bool:
        """Whether embeddings can be generated."""
        return self._available

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        return self._dimension

    def _load_model(self) -> Any:
        """Lazy-load the model on first use."""
        if self._model is not None:
            return self._model
        if not self._available:
            return None

        # Check global cache first
        if self._model_name in _MODEL_CACHE:
            self._model = _MODEL_CACHE[self._model_name]
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model: %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()
            _MODEL_CACHE[self._model_name] = self._model
            logger.info(
                "Embedding model loaded: %s (dim=%d)",
                self._model_name, self._dimension,
            )
        except Exception as exc:
            logger.error("Failed to load embedding model: %s", exc)
            self._available = False
            self._model = None
        return self._model

    async def embed(self, text: str) -> list[float] | None:
        """Return embedding vector for a single text, or None if unavailable."""
        result = await self.embed_batch([text])
        if result and result[0] is not None:
            return result[0]
        return None

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None] | None:
        """Return embeddings for multiple texts. Uses model.encode() with batching."""
        if not self._available or not texts:
            return None

        model = self._load_model()
        if model is None:
            return None

        try:
            # Run in thread pool to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None,
                lambda: model.encode(texts, show_progress_bar=False).tolist(),
            )
            return embeddings
        except Exception as exc:
            logger.error("Embedding failed: %s", exc)
            return None
