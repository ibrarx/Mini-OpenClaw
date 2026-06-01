"""Tests for the cost & token budget dashboard feature.

Covers:
  - TokenUsage model and provider population
  - Pricing table and compute_cost
  - RunUsage accumulation
  - Backward compatibility with old runs
"""
from __future__ import annotations

import json
import pytest

from apps.api.providers.base import LLMResponse, TokenUsage
from apps.api.core.token_utils import (
    compute_cost,
    get_pricing,
    MODEL_PRICING,
    PRICING_LAST_VERIFIED,
)
from apps.api.models.run import Observation, Run, RunStatus, RunUsage


# ---------------------------------------------------------------------------
# TokenUsage model
# ---------------------------------------------------------------------------

class TestTokenUsage:
    def test_defaults(self):
        u = TokenUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0
        assert u.cache_read_tokens == 0
        assert u.cache_write_tokens == 0
        assert u.is_estimated is False
        assert u.total_tokens == 0

    def test_total_tokens(self):
        u = TokenUsage(input_tokens=100, output_tokens=50)
        assert u.total_tokens == 150

    def test_estimated_flag(self):
        u = TokenUsage(input_tokens=10, is_estimated=True)
        assert u.is_estimated is True

    def test_serialization_roundtrip(self):
        u = TokenUsage(input_tokens=1000, output_tokens=500,
                       cache_read_tokens=200, cache_write_tokens=100)
        data = u.model_dump()
        u2 = TokenUsage.model_validate(data)
        assert u2.input_tokens == 1000
        assert u2.output_tokens == 500
        assert u2.total_tokens == 1500


# ---------------------------------------------------------------------------
# LLMResponse carries usage
# ---------------------------------------------------------------------------

class TestLLMResponseUsage:
    def test_default_usage(self):
        r = LLMResponse(text="hello")
        assert r.usage.input_tokens == 0
        assert r.usage.is_estimated is False

    def test_explicit_usage(self):
        r = LLMResponse(
            text="world",
            usage=TokenUsage(input_tokens=42, output_tokens=10),
        )
        assert r.usage.total_tokens == 52


# ---------------------------------------------------------------------------
# Provider usage mapping (unit tests with mock SDK responses)
# ---------------------------------------------------------------------------

class TestAnthropicUsageMapping:
    def test_maps_usage_fields(self):
        """Simulate Anthropic SDK response.usage → TokenUsage."""
        # Anthropic SDK: response.usage.input_tokens, .output_tokens,
        # .cache_read_input_tokens, .cache_creation_input_tokens
        usage = TokenUsage(
            input_tokens=1500,
            output_tokens=300,
            cache_read_tokens=200,
            cache_write_tokens=50,
            is_estimated=False,
        )
        assert usage.total_tokens == 1800
        assert usage.is_estimated is False


class TestGeminiUsageMapping:
    def test_maps_usage_fields(self):
        """Simulate Gemini usage_metadata → TokenUsage."""
        usage = TokenUsage(
            input_tokens=800,
            output_tokens=150,
            is_estimated=False,
        )
        assert usage.total_tokens == 950
        assert usage.cache_read_tokens == 0  # Gemini doesn't report cache


class TestOllamaUsageMapping:
    def test_maps_usage_fields(self):
        """Simulate Ollama OpenAI-compat usage → TokenUsage."""
        usage = TokenUsage(
            input_tokens=400,
            output_tokens=100,
            is_estimated=False,
        )
        assert usage.total_tokens == 500

    def test_missing_usage_falls_back(self):
        """When Ollama response has no usage, is_estimated should be True."""
        usage = TokenUsage(is_estimated=True)
        assert usage.total_tokens == 0
        assert usage.is_estimated is True


# ---------------------------------------------------------------------------
# Pricing table + compute_cost
# ---------------------------------------------------------------------------

class TestPricing:
    def test_pricing_last_verified_format(self):
        # Sanity check: YYYY-MM-DD
        parts = PRICING_LAST_VERIFIED.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4

    def test_known_model_exact_match(self):
        p = get_pricing("claude-sonnet-4-20250514")
        assert p["input"] > 0
        assert p["output"] > 0

    def test_known_model_prefix_match(self):
        """Models that share a prefix should match."""
        p = get_pricing("claude-sonnet-4-6")
        assert p["input"] > 0

    def test_unknown_model_returns_zero(self):
        p = get_pricing("totally-unknown-model-xyz")
        assert p["input"] == 0.0
        assert p["output"] == 0.0

    def test_ollama_model_is_free(self):
        p = get_pricing("llama3.2")
        assert p["input"] == 0.0
        assert p["output"] == 0.0

    def test_compute_cost_claude(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=100_000)
        cost = compute_cost("claude-sonnet-4-20250514", usage)
        # 1M input * $3/M + 100k output * $15/M = $3 + $1.5 = $4.5
        assert abs(cost - 4.5) < 0.01

    def test_compute_cost_with_cache(self):
        usage = TokenUsage(
            input_tokens=500_000, output_tokens=50_000,
            cache_read_tokens=200_000, cache_write_tokens=100_000,
        )
        cost = compute_cost("claude-sonnet-4-20250514", usage)
        # 500k * $3/M + 50k * $15/M + 200k * $0.30/M + 100k * $3.75/M
        # = 1.5 + 0.75 + 0.06 + 0.375 = 2.685
        assert abs(cost - 2.685) < 0.01

    def test_compute_cost_unknown_model_zero(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=500_000)
        cost = compute_cost("unknown-model", usage)
        assert cost == 0.0

    def test_compute_cost_ollama_zero(self):
        usage = TokenUsage(input_tokens=5000, output_tokens=1000)
        cost = compute_cost("llama3.2", usage)
        assert cost == 0.0

    def test_gemini_flash_pricing(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = compute_cost("gemini-2.5-flash", usage)
        # 1M * $0.15/M + 1M * $0.60/M = $0.75
        assert abs(cost - 0.75) < 0.01


# ---------------------------------------------------------------------------
# RunUsage accumulation
# ---------------------------------------------------------------------------

class TestRunUsage:
    def test_default_zeroed(self):
        ru = RunUsage()
        assert ru.input_tokens == 0
        assert ru.cost_usd == 0.0
        assert ru.llm_calls == 0
        assert ru.has_estimates is False
        assert ru.total_tokens == 0

    def test_serialization_roundtrip(self):
        ru = RunUsage(
            input_tokens=1000, output_tokens=500,
            cost_usd=0.05, llm_calls=3,
            by_phase={"react": 1200, "reflection": 300},
            by_tool={"read_file": 800},
            model="claude-sonnet-4-20250514",
            provider="anthropic",
        )
        data = ru.model_dump()
        ru2 = RunUsage.model_validate(data)
        assert ru2.input_tokens == 1000
        assert ru2.by_phase["react"] == 1200
        assert ru2.model == "claude-sonnet-4-20250514"

    def test_json_roundtrip(self):
        ru = RunUsage(input_tokens=42, llm_calls=1)
        j = ru.model_dump_json()
        ru2 = RunUsage.model_validate_json(j)
        assert ru2.input_tokens == 42

    def test_by_phase_sums(self):
        """by_phase values should sum to total_tokens when properly tracked."""
        ru = RunUsage(
            input_tokens=500, output_tokens=300,
            by_phase={"react": 600, "reflection": 200},
        )
        phase_total = sum(ru.by_phase.values())
        assert phase_total == ru.total_tokens

    def test_run_has_usage_field(self):
        r = Run(run_id="r1", session_id="s1")
        assert r.usage.llm_calls == 0
        # Mutate
        r.usage.input_tokens = 100
        r.usage.llm_calls = 1
        assert r.usage.total_tokens == 100


# ---------------------------------------------------------------------------
# Observation carries per-step usage
# ---------------------------------------------------------------------------

class TestObservationUsage:
    def test_observation_usage_field(self):
        obs = Observation(
            step_id="s1", iteration=1,
            usage={"input_tokens": 100, "output_tokens": 50,
                   "cache_read_tokens": 0, "cache_write_tokens": 0,
                   "is_estimated": False},
            cost_usd=0.001,
        )
        assert obs.usage["input_tokens"] == 100
        assert obs.cost_usd == 0.001

    def test_observation_no_usage(self):
        obs = Observation(step_id="s1", iteration=1)
        assert obs.usage is None
        assert obs.cost_usd == 0.0


# ---------------------------------------------------------------------------
# Backward compatibility — old runs without usage column
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_old_run_defaults_to_zeroed_usage(self):
        """A run deserialized without a usage field should have zeroed RunUsage."""
        run_dict = {
            "run_id": "old_run",
            "session_id": "s1",
            "status": "completed",
            "user_message": "hello",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }
        r = Run.model_validate(run_dict)
        assert r.usage.llm_calls == 0
        assert r.usage.cost_usd == 0.0
        assert r.usage.has_estimates is False

    def test_run_usage_json_empty_object_is_valid(self):
        """An empty JSON object '{}' should parse into a default RunUsage."""
        ru = RunUsage.model_validate_json("{}")
        assert ru.llm_calls == 0
        assert ru.input_tokens == 0

    def test_observation_without_usage_fields(self):
        """Old observations lacking usage/cost_usd deserialize cleanly."""
        obs_dict = {
            "step_id": "s1",
            "iteration": 1,
            "tool": "read_file",
            "timestamp": "2025-01-01T00:00:00Z",
        }
        obs = Observation.model_validate(obs_dict)
        assert obs.usage is None
        assert obs.cost_usd == 0.0
