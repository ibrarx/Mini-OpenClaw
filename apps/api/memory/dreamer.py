"""memory/dreamer — Post-run memory consolidation ("Agent Dreams").

Mines episodic memory for strategies (workflow patterns) and preferences
(inferred user traits). Insights are stored as ``pending_review`` and
require user confirmation before they influence planning.

Design decisions:
  - **1D**: Hybrid trigger — background after runs + manual API endpoint
  - **2C**: User-confirmed — insights go to pending_review, not straight to active
  - **3C**: FIFO with reconfirmation — when at cap, lowest-confidence active item
            is evicted if a new insight scores higher
  - **4C**: Lives in memory subsystem (not orchestrator or core)
  - **5A**: Passive context — active insights are injected into planner prompt as
            background info, planner decides whether to use them
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.api.models.memory_item import MemoryType

if TYPE_CHECKING:
    from apps.api.memory.manager import MemoryManager
    from apps.api.memory.retrieval import MemoryRetrieval
    from apps.api.providers.base import LLMProvider

logger = logging.getLogger(__name__)

DREAM_SYSTEM_PROMPT = """You are analyzing a user's interaction history with an AI agent to extract useful patterns.

Review the recent episodes (past interactions) and any existing memories. Identify:

1. **Strategies** — recurring patterns in HOW the user works:
   - Tool sequences they frequently use (e.g., "always lists files before reading them")
   - Workflows they follow repeatedly
   - Problem-solving approaches they prefer

2. **Preferences** — inferred characteristics:
   - Their project's tech stack, structure, file locations
   - Communication style preferences (verbose/concise)
   - Topics they return to frequently

Rules:
- Only extract patterns you're CONFIDENT about (seen 2+ times)
- Keep each insight to 1-2 sentences
- Don't duplicate existing memories
- Don't re-propose rejected insights
- Don't extract trivial facts ("the user asked a question")
- Focus on insights that would help a FUTURE interaction

Respond with ONLY valid JSON (no markdown, no backticks):
{
  "strategies": [
    {"content": "...", "confidence": 0.0}
  ],
  "preferences": [
    {"content": "...", "confidence": 0.0}
  ]
}

If no useful patterns are found, return: {"strategies": [], "preferences": []}
"""


class Dreamer:
    """Consolidates episodic memory into strategies and preferences.

    Called after every N episodes (configurable via ``dream_interval``)
    or manually via the ``/api/memory/dream`` endpoint. Analyses recent
    episodes and existing memories to extract higher-level insights.

    New insights are stored as ``pending_review`` — the user must accept
    or dismiss them before they influence planning (design option 2C).
    """

    def __init__(
        self,
        provider: LLMProvider,
        memory: MemoryManager,
        retrieval: MemoryRetrieval,
        *,
        max_strategies: int = 10,
        max_preferences: int = 10,
        confidence_threshold: float = 0.6,
    ) -> None:
        self._provider = provider
        self._memory = memory
        self._retrieval = retrieval
        self._max_strategies = max_strategies
        self._max_preferences = max_preferences
        self._confidence_threshold = confidence_threshold

    async def dream(self, workspace_id: str = "default") -> dict:
        """Run a dream cycle. Returns counts of new insights proposed.

        Returns
        -------
        dict
            Keys: ``strategies``, ``preferences`` (int counts),
            optionally ``skipped`` or ``error``.
        """
        # 1. Gather recent episodes
        episodes = await self._memory.get_recent_episodes(workspace_id, limit=10)
        if len(episodes) < 3:
            return {"strategies": 0, "preferences": 0, "skipped": "not enough episodes"}

        # 2. Get existing active strategies and preferences to avoid duplicates
        existing_strategies = await self._memory.list_items(workspace_id, "strategy")
        existing_preferences = await self._memory.list_items(workspace_id, "preference")

        # 3. Get rejected contents to avoid re-proposing
        rejected = await self._memory.get_rejected_contents(workspace_id)

        # 4. Also get pending items to avoid duplicating those
        pending = await self._memory.get_pending_insights(workspace_id)

        # 5. Build prompt
        ep_text = "\n".join(f"- {ep.content[:300]}" for ep in episodes)

        existing_parts: list[str] = []
        for s in existing_strategies:
            if s.status.value == "active":
                existing_parts.append(f"- [strategy] {s.content}")
        for p in existing_preferences:
            if p.status.value == "active":
                existing_parts.append(f"- [preference] {p.content}")
        for item in pending:
            existing_parts.append(f"- [pending] {item.content}")
        existing_text = "\n".join(existing_parts) if existing_parts else "None yet."

        rejected_text = "\n".join(f"- {r}" for r in rejected) if rejected else "None."

        content = (
            f"Recent interactions:\n{ep_text}\n\n"
            f"Existing memories (don't duplicate these):\n{existing_text}\n\n"
            f"Previously rejected insights (don't re-propose these):\n{rejected_text}\n\n"
            "What patterns and preferences can you extract?"
        )

        # 6. Call LLM
        from apps.api.providers.base import LLMMessage
        try:
            result, _usage = await self._provider.generate_json(
                messages=[LLMMessage(role="user", content=content)],
                system=DREAM_SYSTEM_PROMPT,
                max_tokens=1024,
                timeout=30.0,
            )
        except Exception as exc:
            logger.warning("Dream cycle failed: %s", exc)
            return {"strategies": 0, "preferences": 0, "error": str(exc)}

        # 7. Store new insights as pending_review
        strategy_count = 0
        for s in result.get("strategies", []):
            conf = s.get("confidence", 0)
            content_text = s.get("content", "")
            if not content_text or conf < self._confidence_threshold:
                continue
            await self._memory.store_dream_insight(
                MemoryType.STRATEGY, content_text, conf, workspace_id,
            )
            strategy_count += 1

        pref_count = 0
        for p in result.get("preferences", []):
            conf = p.get("confidence", 0)
            content_text = p.get("content", "")
            if not content_text or conf < self._confidence_threshold:
                continue
            await self._memory.store_dream_insight(
                MemoryType.PREFERENCE, content_text, conf, workspace_id,
            )
            pref_count += 1

        logger.info(
            "Dream cycle: %d strategies, %d preferences proposed for review",
            strategy_count, pref_count,
        )
        return {"strategies": strategy_count, "preferences": pref_count}
