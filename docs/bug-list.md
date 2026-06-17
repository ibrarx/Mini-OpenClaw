# Bug List — T08 Testing & Hardening

Prioritized list of issues found and fixed during T08.

## P0 — Blocks demo (crashes, data loss)

| # | Description | Status |
|---|-------------|--------|
| 1 | `routes/tools.py` had missing `import logging` and duplicate/broken import of `SkillRegistry` — caused crash on `/api/tools` | **FIXED** |
| 2 | `routes/memory.py` had duplicate imports and referenced nonexistent `MemorySearchRequest` — could crash on import | **FIXED** |
| 3 | All 5 test files referenced APIs that don't exist in the codebase (`RunStep`, `TaskType`, `PlannerResponse`, `validate_step`, `classify_risk`, `MAX_STEPS_PER_RUN`, etc.) — 100% test failure | **FIXED** — all tests rewritten to match actual code |

## P1 — Visible to evaluator (wrong output, UI glitch)

| # | Description | Status |
|---|-------------|--------|
| 4 | `read_file` tool did not detect binary files — reading a `.bin` file would return garbled replacement characters instead of a clear error | **FIXED** — added null-byte detection on first 8 KB |
| 5 | Policy engine allowed empty path `""` — should be denied | **FIXED** — added empty/whitespace check |
| 6 | Policy engine allowed `~/secret.txt` tilde expansion — could escape workspace on some OS | **FIXED** — block paths starting with `~` |
| 7 | Policy engine only blocked Windows metacharacters (`&`, `^`, `%`) on Windows — these should be blocked everywhere for consistent security | **FIXED** — check on all platforms |
| 8 | Policy engine allowed empty command string `""` in `validate_shell` — should be denied | **FIXED** — added empty check |
| 9 | Health endpoint returned minimal info — evaluators need to see API key status, tool list, workspace status, memory count | **FIXED** — enhanced with full diagnostics |
| 10 | `main.py` startup had no validation — no warning if API key is missing, no startup summary | **FIXED** — added full startup validation and logging |

## P2 — Cosmetic or minor (log message, edge case)

| # | Description | Status |
|---|-------------|--------|
| 11 | `seed_demo.py` only created 4 files — evaluators need richer demo content | **FIXED** — now creates 7 files in 4 directories |
| 12 | `export_memory.py` did not export audit log | **FIXED** — now exports `audit_log.json` too |
| 13 | `conftest.py` had `test_db` fixture returning a connection (not needed by any working test) | **FIXED** — replaced with cleaner `make_tool_context` helper |

## Resolved Since T08

These were open at T08 and have since been addressed as the project evolved:

| # | Description | Status |
|---|-------------|--------|
| A | Planner used the synchronous `anthropic.Anthropic` client, blocking the event loop | **RESOLVED** — replaced by the async `LLMProvider` abstraction (Anthropic/Gemini/Ollama), all calls awaited |
| C | No WebSocket support (polling only) | **RESOLVED** — live updates now stream over Server-Sent Events (`GET /api/runs/{id}/stream`) |
| D | No semantic/embedding memory retrieval (keyword only) | **RESOLVED** — hybrid retrieval blends local vector search (`all-MiniLM-L6-v2`) with keyword matching |

## Known Remaining Issues

| # | Description | Severity |
|---|-------------|----------|
| B | `_wait_for_approval` polls the DB every ~1s with a fresh connection — works but not the most efficient pattern | P2 — acceptable for a PoC |
| E | LLM output is non-deterministic; intermittent JSON/truncation issues are mitigated with repair + budgets but can still vary run to run | P2 — inherent to LLM agents |
| F | The evaluation suite is small and illustrative (14 tasks), not a rigorous benchmark | P2 — by design for a course PoC |
