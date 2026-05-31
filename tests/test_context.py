"""Tests for context window management: token estimation, progressive summarization."""
from __future__ import annotations

import json
import pytest

from apps.api.core.token_utils import (
    estimate_tokens,
    get_context_window,
    DEFAULT_CONTEXT_WINDOW,
    CONTEXT_RESERVE_PCT,
)
from apps.api.core.planner import Planner


# ── Token estimation ────────────────────────────────────


class TestEstimateTokens:
    """Test the char/4 heuristic token estimator."""

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 1  # min 1

    def test_short_string(self) -> None:
        # "hello" = 5 chars → 5 // 4 = 1
        assert estimate_tokens("hello") == 1

    def test_medium_string(self) -> None:
        text = "a" * 100
        assert estimate_tokens(text) == 25

    def test_long_string(self) -> None:
        text = "x" * 4000
        assert estimate_tokens(text) == 1000

    def test_realistic_text(self) -> None:
        text = "The quick brown fox jumped over the lazy dog. " * 10
        tokens = estimate_tokens(text)
        # ~460 chars → ~115 tokens
        assert 100 <= tokens <= 130


# ── Context window lookup ───────────────────────────────


class TestGetContextWindow:
    """Test model → context window mapping."""

    def test_exact_match_anthropic(self) -> None:
        assert get_context_window("claude-sonnet-4-6") == 200_000

    def test_exact_match_anthropic_deprecated(self) -> None:
        assert get_context_window("claude-sonnet-4-20250514") == 200_000

    def test_exact_match_gemini(self) -> None:
        assert get_context_window("gemini-2.5-flash") == 1_000_000

    def test_exact_match_ollama(self) -> None:
        assert get_context_window("llama3.2") == 8_192

    def test_prefix_match(self) -> None:
        # "claude-sonnet-4-XXXXX" should match via prefix
        result = get_context_window("claude-sonnet-4-99999999")
        assert result == 200_000

    def test_unknown_model_returns_default(self) -> None:
        assert get_context_window("totally-unknown-model-xyz") == DEFAULT_CONTEXT_WINDOW

    def test_empty_string_returns_default(self) -> None:
        assert get_context_window("") == DEFAULT_CONTEXT_WINDOW


# ── Progressive summarization ───────────────────────────


def _make_observations(n: int, output_size: int = 200) -> list[dict]:
    """Create n fake observations with output of given char size."""
    return [
        {
            "tool": f"tool_{i}",
            "status": "success",
            "output": {"data": "x" * output_size},
            "error": None,
        }
        for i in range(n)
    ]


class TestBuildObservationContext:
    """Test the progressive summarization in Planner._build_observation_context."""

    def _make_planner(self, model: str = "llama3.2") -> Planner:
        """Create a Planner with a mock provider that reports the given model."""

        class FakeProvider:
            def __init__(self, model: str) -> None:
                self.model = model

        # Planner only uses self._provider.model in _build_observation_context
        planner = Planner(provider=None, registry=None)
        planner._provider = FakeProvider(model)  # type: ignore[assignment]
        return planner

    def test_empty_observations(self) -> None:
        planner = self._make_planner()
        result = planner._build_observation_context(
            observations=[],
            system_prompt="You are a planner.",
            user_message="Do something.",
        )
        assert result["compression_level"] == "none"
        assert "None yet" in result["obs_text"]
        assert result["context_window"] == 8_192

    def test_few_observations_no_compression(self) -> None:
        """With a large context window and few observations, no compression."""
        planner = self._make_planner("claude-sonnet-4-6")
        obs = _make_observations(3, output_size=100)
        result = planner._build_observation_context(
            observations=obs,
            system_prompt="System prompt." * 10,
            user_message="User message.",
        )
        assert result["compression_level"] == "none"
        assert result["context_window"] == 200_000

    def test_partial_compression(self) -> None:
        """With a small context window and many observations, partial compression kicks in."""
        planner = self._make_planner("phi3")  # 4096 context window
        # Create enough observations to fill 70-90% of available budget
        # phi3: 4096 tokens, available ~2867, fixed ~90, budget ~2777
        # Each obs after truncation is ~130 tokens, so 18 obs ≈ 2340 > 70% of 2777
        obs = _make_observations(18, output_size=400)
        result = planner._build_observation_context(
            observations=obs,
            system_prompt="System." * 50,
            user_message="User message.",
        )
        assert result["compression_level"] in ("partial", "aggressive")
        # Last 2 observations should still have full output in obs_text
        lines = result["obs_text"].strip().split("\n")
        assert "Result:" in lines[-1]
        assert "Result:" in lines[-2]

    def test_aggressive_compression(self) -> None:
        """With very constrained context, aggressive compression preserves last 2."""
        planner = self._make_planner("phi3")  # 4096 context window
        # Create many observations that exceed 90% of budget
        # Need > 2499 tokens of obs. 25 obs × ~130 tokens each ≈ 3250
        obs = _make_observations(25, output_size=400)
        result = planner._build_observation_context(
            observations=obs,
            system_prompt="Long system prompt. " * 100,
            user_message="User message.",
        )
        assert result["compression_level"] == "aggressive"
        lines = result["obs_text"].strip().split("\n")
        # Last 2 lines should be full (contain "Result:")
        assert "Result:" in lines[-1]
        assert "Result:" in lines[-2]
        # Earlier lines should be one-liners (no "Result:")
        for line in lines[:-2]:
            assert "Result:" not in line

    def test_last_two_always_preserved(self) -> None:
        """Regardless of compression level, the last 2 observations stay full."""
        planner = self._make_planner("phi3")  # 4096 context window
        obs = _make_observations(30, output_size=400)
        result = planner._build_observation_context(
            observations=obs,
            system_prompt="S" * 2000,
            user_message="U" * 500,
        )
        lines = result["obs_text"].strip().split("\n")
        # Last two should have full format
        assert "Result:" in lines[-1]
        assert "Result:" in lines[-2]

    def test_result_contains_required_keys(self) -> None:
        planner = self._make_planner()
        result = planner._build_observation_context(
            observations=_make_observations(2),
            system_prompt="System.",
            user_message="User.",
        )
        assert "obs_text" in result
        assert "token_estimate" in result
        assert "context_window" in result
        assert "compression_level" in result
        assert isinstance(result["token_estimate"], int)
        assert result["token_estimate"] > 0


# ── Observation model ───────────────────────────────────


class TestObservationTokenEstimate:
    """Test that the token_estimate field works on the Observation model."""

    def test_default_zero(self) -> None:
        from apps.api.models.run import Observation

        obs = Observation(step_id="s1", iteration=1)
        assert obs.token_estimate == 0

    def test_set_value(self) -> None:
        from apps.api.models.run import Observation

        obs = Observation(step_id="s1", iteration=1, token_estimate=5000)
        assert obs.token_estimate == 5000

    def test_serialization(self) -> None:
        from apps.api.models.run import Observation

        obs = Observation(step_id="s1", iteration=1, token_estimate=1234)
        data = obs.model_dump()
        assert data["token_estimate"] == 1234


# ── Run model ───────────────────────────────────────────


class TestRunContextWindow:
    """Test that the context_window field works on the Run model."""

    def test_default_zero(self) -> None:
        from apps.api.models.run import Run

        run = Run(run_id="r1", session_id="s1")
        assert run.context_window == 0

    def test_set_value(self) -> None:
        from apps.api.models.run import Run

        run = Run(run_id="r1", session_id="s1", context_window=200_000)
        assert run.context_window == 200_000
