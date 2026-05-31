# Mini-OpenClaw

A lightweight local-first AI agent that converts natural-language requests into safe, auditable tool executions on your local machine.

**Course:** Applied Generative AI — TU Wien
**Group:** _[Group number]_
**Members:** _[Member names]_

---

## Overview

Mini-OpenClaw takes plain-language instructions from a user, routes them through a structured planner (Claude, Gemini, or a local Ollama model), validates every proposed action against a security policy engine, and executes approved steps using a registry of local tools — all within an auditable, inspectable pipeline.

The agent uses a **Hybrid Plan → ReAct → Replan** architecture as its default execution model: before acting, the LLM generates a goal checklist; then it enters a ReAct loop (reason → act → observe) working toward those goals; if too many goals are skipped or progress stalls, the system automatically replans with fresh goals — all visible in the UI. A pure ReAct mode and a legacy plan-and-execute mode are available for comparison.

Key features:

- **Sub-agent delegation** — complex multi-part tasks are decomposed into child runs, each executed by a focused sub-agent with its own iteration budget, approval gates, and real-time SSE streaming in the UI
- **Scheduled tasks** — one-time or recurring tasks via a heap-based scheduler with advance approval, per-run approval, pre-approved tools, and a dedicated Scheduler page with live run history and an approval card for background runs that need user consent
- **Hybrid Plan-ReAct with replanning** — goal checklist generated before execution, tracked live in the UI, with automatic or LLM-requested replanning when the plan goes off-track
- **ReAct loop** with iterative reasoning and real-time adaptation to failures
- **Real-time SSE streaming** — run status, plans, and approvals pushed to the frontend instantly via Server-Sent Events (no polling)
- **User-friendly status announcements** — the agent narrates what it's doing in plain language ("Let me search your files…") instead of showing raw tool names, with full tool traceability preserved in expandable details
- **Hybrid semantic memory** — 70% vector similarity + 30% keyword matching, powered by local sentence-transformers embeddings (no API cost)
- **Three memory layers** — durable facts, episodic task history, and auto-generated conversation summaries
- **Agent Dreams** — post-run memory consolidation that mines episodes for workflow strategies and user preferences, proposed for user review before influencing future planning
- **Saga compensation** — reject a step and all previous write operations are automatically rolled back
- **Budget-aware planning** — the agent sees its iteration budget, prefers batch operations, and works more strategically when budget is low; a live progress bar in the UI shows budget consumption
- **Graceful max-iterations degradation** — when the agent exhausts its iteration budget, it synthesizes a direct answer from collected evidence instead of just summarizing what actions were taken; the run completes successfully if evidence is sufficient
- **Error classification** — transient errors are retried with backoff, permanent errors go straight to the LLM, side-effect errors are surfaced to the user
- **Self-reflection quality gate** — optional critique step where the agent scores its own final answer (completeness, accuracy, clarity). When the score is below threshold and iteration budget remains, the agent re-enters the ReAct loop to take corrective action (re-read files, run additional searches, etc.). Falls back to a text-only rewrite if no budget remains. Live "Reviewing…" status and expandable score breakdown in the UI
- **Retry failed runs** — a one-click retry button appears on failed or cancelled runs, re-submitting the original message without retyping
- **Execution graph** — a real-time DAG visualization in the sidebar showing each run's execution flow: start → tool calls → answer. Delegate nodes branch right with always-visible child run cards. Click any node for a detail popover (with pin mode for comparing steps). Click the graph icon on any past message to load its graph. Animated edge draw-in and node fade-in
- **LLM-provider-agnostic** — swap Claude for Gemini (AI Studio or Vertex AI) or a local Ollama model (or add your own) without touching core code
- **Manifest-driven tool extensibility** — add a tool without rewriting the core agent loop
- **Multi-layer security** — policy engine, command allowlists, and approval gates for risky operations
- **Full audit trail** — every decision logged in an append-only audit table

## Prerequisites

- **Python 3.11+** — [python.org/downloads](https://www.python.org/downloads/)
- **Node.js 18+** and npm — [nodejs.org](https://nodejs.org/)
- **An API key from either**:
  - **Anthropic** (default) — [console.anthropic.com](https://console.anthropic.com/), or
  - **Google Gemini** — [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey), or via **Vertex AI** with GCP credits (see [Switching LLM providers](#switching-llm-providers))
  - **Or no key at all** — use [Ollama](https://ollama.ai) for free local models

  See [Switching LLM providers](#switching-llm-providers) below.

## Quick Start

### macOS / Linux

```bash
# 1. Extract the ZIP (or clone)
unzip mini-openclaw.zip && cd mini-openclaw

# 2. Set up Python environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install backend dependencies
pip install -r requirements.txt

# 4. Install frontend dependencies
cd apps/web && npm install && cd ../..

# 5. Configure API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 6. Start the backend (terminal 1)
python -m uvicorn apps.api.main:app --port 8000 --reload --reload-dir apps --reload-dir scripts

# 7. Start the frontend (terminal 2)
cd apps/web && npm run dev

# 8. Open browser
open http://localhost:5173
```

Or using the Makefile:

```bash
cp .env.example .env    # edit with your API key
make install
make dev
# Open http://localhost:5173
```

### Windows (CMD)

```cmd
:: 1. Extract the ZIP and enter the folder
:: 2. Set up Python environment
python -m venv .venv
.venv\Scripts\activate

:: 3. Install backend dependencies
pip install -r requirements.txt

:: 4. Install frontend dependencies
cd apps\web && npm install && cd ..\..

:: 5. Configure API key
copy .env.example .env
:: Edit .env and add your ANTHROPIC_API_KEY

:: 6. Start the backend (terminal 1)
python -m uvicorn apps.api.main:app --port 8000 --reload --reload-dir apps --reload-dir scripts

:: 7. Start the frontend (terminal 2)
cd apps\web && npm run dev

:: 8. Open browser
start http://localhost:5173
```

Or using the startup script:

```cmd
copy .env.example .env
:: Edit .env and add your API key
start.bat
:: Open http://localhost:5173
```

### Windows (PowerShell)

```powershell
copy .env.example .env
# Edit .env and add your API key
.\start.ps1
# Open http://localhost:5173
```

## Seed the Demo Workspace (optional but recommended)

The seed script creates a realistic **WeatherBot** project in the workspace with 18 files across 5 directories — enough to exercise every tool meaningfully. It also pre-populates memory with facts and episodes so the Memory Browser isn't empty on first launch.

```bash
python scripts/seed_demo.py
```

| Flag | What it does |
|------|-------------|
| *(no flag)* | Creates workspace files (skips existing), replaces seed memory only |
| `--clean` | Wipes workspace + seed memory, then recreates. Agent-created memory is preserved. |
| `--clean-all` | Full reset: wipes workspace + ALL memory (seed and agent-created), then recreates. |

The seeded workspace contains TODO/FIXME/BUG markers scattered across 10 files, making `search_in_files` demos immediately interesting. Run `--clean-all` before a screencast recording for a fresh start.

## Try These Demo Commands

Once the app is running, type these into the chat:

### Basic tools
1. **"List files in the workspace"** — safe tool, auto-executes
2. **"Read the README file"** — reads and displays file content
3. **"Create a file called notes.txt with a summary of the project"** — triggers approval flow
4. **"Search for TODO in all files"** — grep-like search across workspace
5. **"Remember that I prefer dark mode"** — stores a fact in memory, visible in Memory Browser

### Memory — semantic recall
6. **"Remember that I prefer VS Code as my editor"** — stores a fact, auto-indexed for semantic search
7. **"What IDE should I open?"** — the agent recalls "VS Code" even though you said "editor" not "IDE" (semantic match, not keyword)
8. **"Remember my project uses PostgreSQL"** → then **"Help me set up the database config"** — the planner already knows it's PostgreSQL, doesn't ask

### Verifying semantic search in the Memory tab
9. After step 6, go to **Memory → search "what IDE"**:
   - **Hybrid** mode → finds "VS Code" (semantic + keyword)
   - **Keyword** mode → does NOT find it (no word overlap between "IDE" and "editor")
   - **Vector** mode → finds it (pure semantic similarity)

   This proves memory is semantic, not just keyword matching.

### ReAct loop — adaptation and recovery
10. **"Read the file config.yaml and summarize it"** — file doesn't exist, LLM adapts (lists files, discovers what's available, gives an informed answer instead of just failing)
11. **"Read the README and tell me what this project is about"** — multi-step: may list_files first to find the README, then read it, then summarize

### Goal checklist and replanning
12. **"Read report.pdf, summarize it, then create a follow-up document"** — goals appear in the UI; report.pdf doesn't exist, so goals get skipped and auto-replan triggers with a new plan
13. **"Find all Python test files, run them, and report results"** — "run tests" goal is impossible (no `python` in the shell allowlist), forcing the agent to replan toward something achievable
14. **"Explore the workspace and tell me what this project does"** — watch the goal checklist track progress as the agent works through "list files → read key files → summarize"

### Saga compensation — rollback on rejection
15. **"Create files called a.txt, b.txt, and c.txt with some content"** — approve the first two, then **reject** the third. The first two files are automatically deleted (saga rollback). Check the workspace to verify they're gone.

### Error classification
16. **"Read /etc/passwd"** — policy denial (path outside workspace), LLM sees the denial and explains why it can't help

### Retry failed runs
17. Temporarily set an invalid API key in `.env` and restart the backend. Send any message — it will fail. A **↻ Retry** button appears below the error message. Fix the API key, restart, and click Retry — the original message is re-submitted automatically without retyping.

### Auto-generated summaries
18. Run 5 different tasks (steps 1–5 above). After the 5th completes, check **Memory → Summaries** — a conversation summary should appear, auto-generated by the LLM from your recent interactions.

### Agent Dreams — pattern discovery
19. After running 5+ tasks, click the **✨ Dream** button in the Memory Browser toolbar. The agent analyses your recent episodes and proposes strategies and preferences.
20. **Review pending insights** — cards appear at the top of the Memory Browser with Accept / Dismiss / Edit buttons. Accept the ones that look right, dismiss the noise, or edit before accepting.
21. Run another task (e.g., *"List files and read the README"*) — the planner's context now includes your accepted strategies and preferences under "Known Strategies" and "Inferred Preferences" sections.
22. Check the **Strategies** and **Preferences** tabs to see all accepted insights. Rejected ones are excluded from future dream proposals.

### Self-reflection quality gate
23. Enable self-reflection: set `REACT_SELF_REFLECT=true` in `.env` and restart the backend.
24. **"Read every file in the workspace and give me a complete summary of the entire project — include all file names, their purposes, and any TODOs you find."** — the agent will likely give an incomplete first answer. The self-check flags it, and the agent **re-enters the ReAct loop** to call more tools (re-read files, run searches). Watch the iteration count jump and look for the blue **"agent retried"** pill on the self-check badge. The final answer will be more thorough than the first attempt.
25. **"Read the README and summarize it"** — if the answer passes the quality threshold, a green self-check badge appears (e.g., 85%). Click it to expand the score breakdown (completeness, accuracy, clarity).
26. To force a text-only fallback, set `REACT_MAX_ITERATIONS=1` and repeat the command. With no budget for re-entry, the self-check rewrites the prose instead — look for the violet **"answer rewritten"** pill.

### Sub-agent delegation
27. **"Delegate reading all the Python files to a sub-agent, then use its findings to create a summary document."** — the parent agent spawns a child run (visible as a purple "sub-agent" badge), the child reads and analyses all files, then the parent uses the child's findings to write a summary. Approval is requested before delegation starts.
28. **"First, search all files for TODO comments and list them. Separately, read the README and create a summary. Do these as independent sub-tasks."** — the agent spawns **two** sub-agents, each handling one independent sub-task. Both child runs stream their progress in real-time within the parent's observation timeline.
29. **"Find all Python files and summarize each one, and also search for bugs or TODOs across the codebase"** — the "and also" joining two unrelated tasks triggers delegation without needing to explicitly say "delegate".
30. Expand a delegation observation row — the nested **Sub-agent** card shows the child's task description, iteration count, individual observation steps, and final response. The child run also appears separately in the Run History tab.

### Scheduled tasks — recurring and one-time

The agent can schedule tasks for future or recurring execution via the `schedule_task` tool. A dedicated **Scheduler** page shows all tasks with live status, run history, and inline approval cards.

**Recurring task (safe tools — fully autonomous):**

31. **"Every 2 minutes, list all files in the workspace and tell me the total count"** — approve the scheduling step → navigate to the Scheduler tab → watch the badge appear as runs complete → expand "View runs" to see each run's output. Uses only safe tools, so no further approval needed.

**Recurring task with pre-approved writes (approve once, runs autonomously):**

32. **"Every 5 minutes, read the README and write a one-line summary to workspace-summary.txt. Approve all future runs automatically."** — the LLM pre-approves `write_file` with `approve_all_runs=true`. One approval card appears at scheduling time. All subsequent runs auto-execute. The Scheduler page shows the amber `write_file` badge with "(all runs auto-approved)".

**Recurring task with per-run approval (approve each execution):**

33. **"Every 2 minutes, read the README and write a one-line summary to workspace-summary.txt. Ask me for approval each time."** — the LLM sets `approve_all_runs=false`. Every run triggers an approval card on the Scheduler page. An amber **"!"** badge pulses on the Scheduler nav tab when approval is needed.

**One-time scheduled task:**

34. **"In 1 minute, list all files in the workspace and tell me the count"** — the task fires once and its status changes to "Completed". Check the Scheduler page to see the result in the run history.

**Search-based recurring (output changes between runs):**

35. **"Every 3 minutes, search for TODO comments in all files and count how many there are"** — add a `# TODO: fix this` to a file between runs and watch the count change. Good for demonstrating that each run is independent.

**Scheduler page features to demonstrate:**

36. **Pause/Resume** — create a recurring task, let it run 2–3 times, hit **Pause**. Verify runs stop. Hit **Resume** — runs restart on schedule.
37. **View runs** — expand a task's run history. Click a run to see the full response. Change the dropdown to "Last 10" or "Last 25" to see more.
38. **Nav badge** — leave the Scheduler page while tasks are running. A green badge appears on the Scheduler tab showing the count of new (unseen) runs. Navigate back → badge clears.
39. **Delete** — delete a task and verify it disappears from the list.

### Execution graph — visual DAG sidebar

The execution graph renders a real-time directed acyclic graph (DAG) in the right sidebar during and after runs. Each tool call is a node, edges animate in with draw-in effects, and delegate nodes branch visually with inline child run cards.

40. **Run any multi-step query** (e.g., *"Read the README and summarize it"*) — watch the sidebar graph build in real-time: Start → read_file ✓ → Answer ✓ with animated edges between nodes.
41. **Click any node** in the graph — a popover appears showing tool arguments, result JSON, reasoning, and timing. Click the **pin icon** to keep the popover open while clicking other nodes (for comparing steps).
42. **Delegation branching** — run *"Search for TODOs and separately summarize the README as independent sub-tasks"* — delegate nodes indent right with a purple left-border, and child run cards render inline showing the sub-agent's observations.
43. **Past run graphs** — scroll up to a completed message. Click the small **↗ graph** link at the bottom of the message. The sidebar loads that run's execution graph. Click ✕ in the footer to dismiss.
44. **Error paths** — run something that fails or gets denied. Error nodes show red borders and dashed edges. The graph makes the failure path visually obvious.

## Execution Modes

### Hybrid Plan → ReAct → Replan (default)

When `REACT_USE_GOALS=true` (the default when goals are enabled), the agent runs in three phases:

**Phase 1 — PLAN:** Before the ReAct loop starts, the LLM generates a goal checklist (e.g., "1. Find the file, 2. Read it, 3. Summarize contents"). Goals are displayed in the UI with live status tracking.

**Phase 2 — REACT:** The agent enters the standard think → act → observe loop. After each tool execution, goal statuses update automatically based on what the LLM reports as completed or skipped. The first pending goal is marked as in-progress.

**Phase 3 — REPLAN:** If the original plan goes off-track, replanning triggers in two ways:
- **LLM-requested:** The LLM can explicitly return `action: "replan"` when it realizes the current goals are wrong
- **Auto-replan:** The system triggers replanning when >50% of goals are skipped, or when the agent is past halfway on iterations with zero goals completed

After replanning, completed goals are preserved and new goals are appended. The replan count is shown in the UI.

```
User: "Read report.pdf, summarize it, then create a follow-up document"

PLAN → Goals: [1. Find report.pdf, 2. Read report.pdf, 3. Summarize, 4. Create follow-up]

Iteration 1: list_files(".")         → report.pdf not found
Iteration 2: search_in_files(".")    → no matches
             → 3 of 4 goals now impossible → AUTO-REPLAN

REPLAN → New goals: [1. ✓ Searched workspace (preserved), 2. Explain file not found, 3. Suggest next steps]

Iteration 3: final_answer → "report.pdf doesn't exist. Here are the files I found..."
```

### Pure ReAct (no goals)

Set `REACT_USE_GOALS=false` in `.env` to disable goal generation and replanning. The agent iterates: **Think → Act → Observe**, up to a configurable maximum number of iterations. Each iteration, the LLM decides whether to call a tool or give a final answer based on all previous observations.

```
User: "Read config.yaml and summarize it"

Iteration 1: THINK → read_file("config.yaml")
             ACT   → execute read_file
             OBSERVE → error: "File not found"

Iteration 2: THINK → list_files(".")           ← LLM adapts
             ACT   → execute list_files
             OBSERVE → success: ["README.md", "src/main.py"]

Iteration 3: THINK → final_answer              ← LLM decides task is done
             "config.yaml doesn't exist. Available files: README.md, src/main.py"
```

### Plan-and-execute (legacy)

Set `USE_REACT=false` in `.env`. The LLM generates a complete plan upfront, then steps execute sequentially. If step 2 fails, there's no recovery — the run fails.

### User-friendly status announcements

During execution, the agent narrates each step in plain language instead of showing raw tool names and status codes:

```
User: "Find all TODO comments in my project"

[spinner] Let me look through your workspace to find what's there...
  ✓ 1  Let me see what files are in your workspace...     list_files
[spinner] Now I'll search across your files for TODO comments...
  ✓ 2  Let me search your files for 'TODO'...             search_in_files
  ✓ 3  Done

"I found 12 TODO comments across 5 files..."
```

Each observation row shows the friendly announcement as the primary label with the actual tool name as a badge on the right. Clicking any row expands it to reveal the full trace: internal reasoning, tool arguments, and raw result output. This gives evaluators and developers full traceability while keeping the default view clean for end users.

The Run History tab shows the same level of detail — expand any past run to see its full observation timeline with expandable tool traces.

## Failure Handling

### Error classification

Every tool error is classified into one of three categories, and the executor responds differently to each:

| Error Kind | Examples | Executor Response |
|---|---|---|
| **Transient** | Network timeout, disk full, rate limit | Retry with exponential backoff (if tool is idempotent) |
| **Permanent** | File not found, path outside workspace, bad credentials | Never retry — feed error to LLM as observation |
| **Side-effect** | Action partially succeeded but downstream broke (e.g., email sent but confirmation failed) | Never retry — surface to user, log as non-reversible |

The retry decision combines the tool's `retry_policy` (declares `max_retries` and `idempotent`) with the `error_kind` from the result. A permanent error is never retried even if the tool allows retries.

### Saga compensation

When a user **rejects** an approval in the ReAct loop, the orchestrator runs compensation in reverse order on all previously completed mutating steps:

| Tool | Compensation action |
|---|---|
| `write_file` (create mode) | Delete the created file |
| `write_file` (overwrite mode) | Restore from `.bak` backup |
| `write_file` (append mode) | Log as non-reversible |
| `remember_fact` | Soft-delete memory items created by this run |
| Read-only tools | No-op (`not_applicable`) |

### Loop detection

If the LLM gets stuck calling the same tool with identical arguments repeatedly (e.g., `list_files(".")` ten times in a row), two layers of defense kick in:

| Layer | Trigger | Action |
|---|---|---|
| **Soft warning** | `REACT_DUPLICATE_CAP` consecutive identical tool+args calls (default: 3) | A `_system` observation is injected telling the LLM it must try a different tool, different arguments, or give a `final_answer` |
| **Hard block** | LLM ignores the warning and tries the same call again | Execution is short-circuited — a "Blocked: loop detected" error observation is returned without running the tool |

Combined with `REACT_MAX_ITERATIONS` (default: 10), this prevents runaway loops from burning API credits. Both values are configurable via `.env`.

### Budget awareness

Every ReAct iteration, the orchestrator injects a budget line into the LLM prompt: `"Budget: step 3 of 10 (7 remaining)"`. When remaining steps fall below the configured threshold (`REACT_BUDGET_WARN_PCT`, default 30%), a `⚠ LOW BUDGET` warning is appended, nudging the LLM to prioritize high-value actions over speculative exploration. The warning is an efficiency nudge, not a stop signal — the agent keeps working but focuses on actions that directly complete the task. If the agent exhausts its budget, the graceful max-iterations degradation (below) catches it automatically.

The frontend shows a matching **progress bar** below the iteration counter. The bar transitions from green → amber → red as budget depletes, pulses while the agent is thinking, and displays a "Low budget" badge when the warning threshold is reached. This gives evaluators a visual sense of where the agent is in its budget without needing to read log output.

To test budget pressure visually, set `REACT_MAX_ITERATIONS=5` in `.env` and ask a multi-step question like *"Read all files in the workspace and summarize the project."*

### Context window management

The ReAct loop sends all previous observations to the LLM on every iteration. Without limits, the prompt grows unboundedly and can exceed the model's context window — especially critical for local models with 4K–8K context limits.

Mini-OpenClaw manages this with three mechanisms:

**Token estimation.** LLMs process text as tokens (sub-word fragments), not characters. Exact tokenization requires model-specific tokenizers like `tiktoken`, which add dependencies and complexity. Mini-OpenClaw uses a lightweight heuristic instead: **1 token ≈ 4 characters** of English text. This ratio holds reasonably well across most tokenizers (GPT-style BPE averages ~3.5–4.5 chars/token for English prose). The estimate is used only for budget management — deciding when to compress observations — not for billing or exact measurement, so ±20% accuracy is sufficient. The implementation lives in `core/token_utils.py` (`estimate_tokens()`). A built-in lookup table maps model names to their context window sizes (e.g. `claude-sonnet-4` → 200K, `llama3.2` → 8K, `phi3` → 4K). Unknown models fall back to a conservative 8K default.

**Progressive summarization.** Before each ReAct iteration, the planner's `_build_observation_context()` method calculates a token budget (context window minus 30% reserve for the response, minus system prompt and user message), then decides how to format observations:

| Context pressure | Strategy | What the LLM sees |
|-----------------|----------|--------------------|
| < 70% of budget | **Full context** — no compression | All observations with complete tool output |
| 70–90% of budget | **Partial compression** — summarize old steps | Observations older than the last 3 reduced to one-liners (`[N] tool: status`), last 3 kept in full |
| > 90% of budget | **Aggressive compression** — preserve only recent context | All but the last 2 observations reduced to one-liners, last 2 kept in full |

The last 2 observations are always preserved in full, ensuring the LLM has immediate context for its next decision.

**UI visibility.** The frontend shows a context window progress bar alongside the iteration budget bar. The bar displays the model name, token usage, and context window size. When compression activates, a subtitle appears below the bar:

- **Partial compression** — amber: *"Older steps summarized to save context"*
- **Aggressive compression** — red: *"Only last 2 steps in full detail — earlier steps heavily compressed"*
- **Overflow** — red: *"Context window exceeded — output quality may degrade"*

The context bar is silent during normal operation (the common case for Claude's 200K window) and only surfaces when it matters.

**Testing compression.** To see compression in action with a large-context model, set `CONTEXT_WINDOW_OVERRIDE=4096` in `.env` and run a multi-step query. The override forces the planner to treat the model as if it has a 4K context window, triggering progressive summarization within a few iterations.

## Switching LLM providers

Mini-OpenClaw is LLM-provider-agnostic. The planner talks to an abstract
`LLMProvider` interface (see [`docs/provider-abstraction.md`](docs/provider-abstraction.md));
concrete providers are plug-in modules. Three are shipped today: **Anthropic
Claude** (default), **Google Gemini**, and **Ollama** (local models).

To switch, edit `.env`:

```dotenv
# Use Anthropic (default)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=claude-sonnet-4-6

# OR use Gemini (AI Studio — API key)
LLM_PROVIDER=gemini
GEMINI_API_KEY=AI...
# GEMINI_MODEL=gemini-2.5-flash

# OR use Gemini (Vertex AI — GCP credits)
LLM_PROVIDER=gemini
VERTEX_AI=true
GCP_PROJECT=your-gcp-project-id
GCP_LOCATION=us-central1
# GEMINI_MODEL=gemini-2.5-flash

# OR use Ollama (free, no API key)
LLM_PROVIDER=ollama
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL=llama3.2
```

> **Using GCP credits with Vertex AI:** Vertex AI routes through `aiplatform.googleapis.com` instead of `generativelanguage.googleapis.com`. You need to: (1) run `gcloud auth application-default login`, (2) enable the Vertex AI API: `gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID`, and (3) set `VERTEX_AI=true` with your `GCP_PROJECT` in `.env`. The `GEMINI_API_KEY` is ignored in Vertex AI mode.

Restart the backend. Verify with:

```bash
curl http://localhost:8000/api/health
```

You should see `"llm_provider": "gemini"` (or `"anthropic"` or `"ollama"`) and
`"api_key_configured": true`.

### Ollama (Local Models — Free, No API Key)

1. Install Ollama: https://ollama.ai
2. Pull a model: `ollama pull llama3.2`
3. Set in `.env`:
   ```
   LLM_PROVIDER=ollama
   OLLAMA_MODEL=llama3.2
   ```
4. Start Mini-OpenClaw normally — it connects to `localhost:11434`

Recommended models:
- `llama3.2` — Best balance of speed and quality for agent tasks
- `mistral` — Fast, good at following JSON instructions
- `codellama` — Best for code-heavy workspaces
- `phi3` — Smallest, runs on 8GB RAM machines

### Adding another provider

To plug in OpenAI / Ollama / Groq / DeepSeek / local models, see the
five-step recipe in [`docs/provider-abstraction.md`](docs/provider-abstraction.md).
None of the planner, orchestrator, policy engine, or tool code needs to
change.

## Architecture

Mini-OpenClaw follows a run-centric architecture: every user request becomes a **run** with discrete steps, each validated and logged.

```
User message
  → Orchestrator
    → Planner (ReAct step: reason about observations, pick next action)
    → Policy Engine (classify: safe / approval-required / forbidden)
    → Executor (validate → execute with retry → observe)
    → Memory Manager (persist useful context)
    → Audit Logger (append-only log of every decision)
    → Event Emitter (push status via SSE to connected frontends)
  → Final answer (or next iteration)
```

The **ReAct loop** replaces the legacy plan-all-upfront model. Each iteration persists observations to SQLite so the run survives approval pauses and server restarts. The **saga pattern** enables rollback when users reject mid-run. The **error classification** system ensures transient failures are retried while permanent failures are immediately fed back to the LLM.

See [docs/architecture.md](docs/architecture.md) for the full design and [docs/provider-abstraction.md](docs/provider-abstraction.md) for the LLM provider layer.

### Sub-agent delegation

When a user request contains multiple independent sub-tasks, the agent can delegate each to a focused **child run** via the `delegate_task` tool. This enables multi-agent orchestration within the existing run-centric architecture.

```
User: "Search for TODO comments AND summarize the README"

Parent run (3 iterations):
  ├── Step 1: delegate_task("Search for TODO comments")
  │     └── Child run_abc (2 iterations):
  │           ├── search_in_files(".", "TODO")  → 12 matches
  │           └── final_answer → "Found 12 TODOs..."
  ├── Step 2: delegate_task("Read and summarize README.md")
  │     └── Child run_def (2 iterations):
  │           ├── read_file("README.md")  → content
  │           └── final_answer → "The project is..."
  └── Step 3: final_answer → Combined summary from both sub-agents
```

**Design decisions:**

- **Approval required** — the user sees "Let me hand this sub-task off to a focused agent…" and approves before the child spawns. This makes delegation visible and auditable.
- **Synchronous execution** — the parent awaits the child's completion directly (no polling). Simple, no race conditions.
- **Child restrictions** — children cannot delegate further, write memory, trigger self-reflection, or run Agent Dreams. They are read-and-report agents.
- **All tools available** — children can use `write_file` and `run_shell_safe` with their own approval gates, so the user retains full control over risky actions.
- **Depth limit** — configurable max nesting (default: 2 levels). Children per parent is also capped (default: 3).
- **Real-time streaming** — each child run emits its own SSE events. The frontend subscribes to the child's stream and renders a nested observation timeline inside the parent's delegation step.
- **Cancellation cascade** — cancelling the parent automatically cancels all active children.

## Memory System

Mini-OpenClaw has a five-layer memory system with hybrid semantic search, designed so the agent remembers user preferences, learns from past tasks, discovers workflow patterns, and builds up context over time.

### Memory types

| Type | What it stores | Created by | Example |
|------|---------------|------------|---------|
| **Fact** | Durable user or workspace preferences | User via `remember_fact` tool | "User prefers VS Code", "Project uses PostgreSQL" |
| **Episode** | Record of a completed task with tools used and outcome | System, automatically after each run | "User asked to list files → list_files → found 12 items" |
| **Summary** | Compressed overview of recent interactions | System, auto-generated every N runs via LLM | "The user is working on a thesis about NLP. Prefers Python." |
| **Strategy** | Inferred workflow pattern discovered across multiple runs | Agent Dreams, confirmed by user | "User typically lists files before reading them" |
| **Preference** | Inferred user or project trait | Agent Dreams, confirmed by user | "User's project uses Python with pytest, source in src/" |

Facts persist until manually deleted. Episodes accumulate indefinitely. Summaries are auto-generated every `SUMMARY_INTERVAL` completed runs (default: 5) and the system keeps the `MAX_SUMMARIES` most recent (default: 3). Strategies and preferences are proposed by Agent Dreams and must be accepted by the user before they influence planning.

### Agent Dreams — memory consolidation

Agent Dreams is a post-run memory consolidation process inspired by how sleep helps humans consolidate learning. After every N completed runs (configurable via `DREAM_INTERVAL`, default: 5), the agent analyses its recent episodes and proposes higher-level insights:

- **Strategies** — recurring workflow patterns: "User always lists files before reading them", "User searches for TODOs before writing reports"
- **Preferences** — inferred user or project traits: "User's project uses Python 3.13 with pytest", "User prefers concise output"

These insights go through a **user review flow** rather than being auto-accepted:

1. The dream cycle extracts candidates and stores them as `pending_review`
2. Pending insights appear as cards in the Memory Browser with **Accept**, **Dismiss**, and **Edit & Accept** buttons
3. Accepted insights are promoted to `active` and included in the planner's context for future runs
4. Dismissed insights are marked `rejected` and excluded from future dream proposals

This design follows the same "propose → review → approve" philosophy as the tool approval system: the agent never acts on inferred knowledge without user consent.

**Trigger modes:**
- **Automatic** — fires as a background task every `DREAM_INTERVAL` episodes (user never waits)
- **Manual** — click the ✨ Dream button in the Memory Browser, or call `POST /api/memory/dream`

**Capacity management (FIFO with reconfirmation):** When the number of active strategies reaches `DREAM_MAX_STRATEGIES` (default: 10), the lowest-confidence item is evicted if a new insight scores higher. Same for preferences with `DREAM_MAX_PREFERENCES`.

**Confidence threshold:** Only insights with LLM confidence ≥ `DREAM_CONFIDENCE_THRESHOLD` (default: 0.6) are proposed. Lower-confidence observations are silently discarded.

### Hybrid search (semantic + keyword)

Memory search uses a hybrid approach inspired by OpenClaw:

- **70% vector similarity** — text is embedded using `all-MiniLM-L6-v2` (384-dim, runs locally on CPU, no API cost) and compared via cosine similarity
- **30% keyword matching** — traditional SQL LIKE-based word overlap

This means searching for "what IDE" finds a fact that says "User prefers VS Code as their editor" — the words don't overlap, but the meaning does. The Memory Browser in the UI lets you switch between Hybrid, Keyword, and Vector modes to compare results.

If `sentence-transformers` is not installed, the system gracefully degrades to keyword-only search without crashing.

### How memory flows into the planner

Before every planning/reasoning call, the orchestrator builds a structured context block:

```
## Known Facts About User
- Preferred editor: VS Code
- Project uses PostgreSQL

## Known Strategies (how the user works)
- User typically lists files before reading them
- User searches for TODOs before writing reports

## Inferred Preferences
- User's project uses Python with pytest, source in src/

## Relevant Past Context
- [2 hours ago] Listed files in workspace — found 12 Python files
- [yesterday] User asked to summarize README.md — created summary.txt

## Conversation Summary
User is working on a thesis project involving NLP. Prefers concise responses.
```

This context is injected into the LLM system prompt with explicit instructions to use it, so the agent doesn't ask questions it already knows the answer to. Strategies and preferences are only included when they have `active` status — pending and rejected insights are excluded.

## Available Tools

| Tool | Description | Risk Level | Approval Required |
|------|-------------|------------|-------------------|
| `list_files` | List files and directories in the workspace | Safe | No |
| `read_file` | Read text files from the workspace — supports single (`path`) or batch (`paths`) mode with configurable character budgets | Safe | No |
| `write_file` | Create, overwrite, or append to a file | Medium | Yes |
| `search_in_files` | Search for patterns across text files | Safe | No |
| `run_shell_safe` | Execute allowlisted commands (pwd, ls, find, cat, grep) | Medium–High | Yes |
| `remember_fact` | Store a durable fact in memory | Safe | No |
| `search_memory` | Query stored facts, episodes, and summaries | Safe | No |
| `delegate_task` | Spawn a sub-agent to handle an independent sub-task — child runs with own iteration budget, restricted tool set (no delegation, no memory writes), and real-time SSE streaming | Medium | Yes |

## Security Model

All proposed actions pass through a four-layer security model: (1) the planner may only reference registered tools with validated JSON schemas, (2) the policy engine enforces workspace path boundaries and shell command allowlists, (3) risky actions require explicit user approval tied to the exact step payload, and (4) an append-only audit log records every decision for post-hoc inspection. See [docs/threat-model.md](docs/threat-model.md) for the full threat model.

## Adding a New Tool

1. Create a new Python file in `apps/api/skills/` (e.g., `my_tool.py`)
2. Implement the `BaseTool` abstract class with `manifest()` and `execute()` methods
3. Define the tool manifest: name, description, risk level, input/output schemas
4. Optionally implement `validate()`, `compensate()`, and `retry_policy` for full ReAct support
5. Restart the server — the skill registry auto-discovers it

No changes to the orchestrator, policy engine, or executor code are required.

## Configuration

All settings are read from the `.env` file (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key | _(required if using Anthropic)_ |
| `GEMINI_API_KEY` | Your Google Gemini API key | _(required if using Gemini AI Studio)_ |
| `VERTEX_AI` | Use Vertex AI endpoint instead of AI Studio (requires GCP auth) | `false` |
| `GCP_PROJECT` | GCP project ID (required when `VERTEX_AI=true`) | _(empty)_ |
| `GCP_LOCATION` | GCP region for Vertex AI | `us-central1` |
| `LLM_PROVIDER` | Which LLM backend to use | `anthropic` |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama model to use | `llama3.2` |
| `WORKSPACE_ROOT` | Directory the agent operates in | `./workspace` |
| `DATABASE_PATH` | SQLite database file path | `./mini_openclaw.db` |
| `ANTHROPIC_MODEL` | Claude model to use | `claude-sonnet-4-6` |
| `GEMINI_MODEL` | Gemini model to use | `gemini-2.5-flash` |
| `USE_REACT` | Use iterative ReAct loop (`true`) or legacy plan-and-execute (`false`) | `true` |
| `REACT_MAX_ITERATIONS` | Maximum think→act→observe iterations per run | `10` |
| `REACT_DUPLICATE_CAP` | Block after N consecutive identical tool+args calls (minimum: 2) | `3` |
| `REACT_USE_GOALS` | Generate a goal checklist before the ReAct loop (hybrid Plan→ReAct) | `false` |
| `REACT_MAX_REPLANS` | Maximum mid-loop replans (0 = goals only, no replanning; clamped 0–5) | `2` |
| `REACT_BUDGET_WARN_PCT` | Warn the LLM when this percentage of the iteration budget remains (clamped 10–80). Nudges the agent toward efficiency (not a hard stop). Triggers the UI progress bar turning red. | `30` |
| `CONTEXT_WINDOW_OVERRIDE` | Override the auto-detected context window size (in tokens). `0` = auto-detect from model name. Set to e.g. `4096` to test compression behavior with large-context models. | `0` |
| `REACT_READ_FILE_MAX_BATCH` | Maximum files per batch `read_file` call | `10` |
| `REACT_READ_FILE_MAX_CHARS` | Maximum total output characters per `read_file` call | `50000` |
| `REACT_OBSERVATION_MAX_CHARS` | Max characters kept per tool observation (except `read_file`) fed back to the planner. Increase if `search_in_files` or `run_shell_safe` results are truncated | `1000` |
| `REACT_READ_FILE_OBS_SINGLE` | Max characters kept per single-file `read_file` observation fed back to the planner | `3000` |
| `REACT_READ_FILE_OBS_BATCH` | Max characters kept per file in a batch `read_file` observation fed back to the planner | `2000` |
| `REACT_SELF_REFLECT` | Enable self-reflection: the agent critiques its own final answer and re-enters the ReAct loop to take corrective action if quality is low. Falls back to text rewrite if no iteration budget remains | `false` |
| `REACT_REFLECT_QUALITY_THRESHOLD` | Quality score (0.0–1.0) below which the agent re-enters the loop or rewrites its answer | `0.7` |
| `SUMMARY_INTERVAL` | Auto-generate a summary every N completed runs (0 = disable) | `5` |
| `MAX_SUMMARIES` | Number of summaries to keep (oldest pruned) | `3` |
| `DREAM_INTERVAL` | Run Agent Dreams every N episodes to propose strategies and preferences (0 = disable) | `5` |
| `DREAM_MAX_STRATEGIES` | Maximum active strategies to keep; lowest-confidence evicted at cap | `10` |
| `DREAM_MAX_PREFERENCES` | Maximum active preferences to keep; lowest-confidence evicted at cap | `10` |
| `DREAM_CONFIDENCE_THRESHOLD` | Minimum LLM confidence (0.0–1.0) for a dream insight to be proposed | `0.6` |
| `DELEGATE_ENABLED` | Enable/disable the `delegate_task` tool | `true` |
| `DELEGATE_APPROVAL_REQUIRED` | Require user approval before spawning a child run (`true` = safer demo, `false` = smoother UX) | `true` |
| `DELEGATE_MAX_DEPTH` | Maximum nesting level for delegation (0 = no delegation, 1 = children only, 2 = grandchildren) | `2` |
| `DELEGATE_MAX_CHILDREN` | Maximum child runs a single parent can spawn | `3` |
| `DELEGATE_MAX_CHILD_ITERATIONS` | Iteration cap per child run (hard max regardless of agent request) | `5` |
| `SCHEDULER_ENABLED` | Enable/disable the scheduled task system and its `schedule_task` tool | `true` |
| `SCHEDULER_MAX_TASKS` | Maximum number of active scheduled tasks allowed at once | `20` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `BACKEND_PORT` | Backend server port | `8000` |

## Running Tests

```bash
# macOS / Linux
make test

# Any OS
python -m pytest tests/ -v
```

The test suite covers:

| Test file | What it tests | Count |
|-----------|--------------|-------|
| `test_context.py` | Token estimation, context window lookup, progressive summarization, compression levels | 22 |
| `test_delegation.py` | Sub-agent delegation: child run creation, workspace inheritance, depth limits, children limits, iteration caps, result flow-back, tool restrictions | 7 |
| `test_memory_semantic.py` | Hybrid search, embedding, vector store, planner wiring, summaries | 44 |
| `test_policy.py` | Path validation, shell blocking, injection detection, risk classification | 38 |
| `test_providers.py` | Anthropic/Gemini/Ollama provider translation, factory, JSON extraction | 48 |
| `test_tools.py` | Each V1 tool in isolation (including batch read_file) | 42 |
| `test_react.py` | ReAct loop, hybrid Plan-ReAct, goal tracking, replanning, saga compensation, error classification, loop detection, approval flow, batch reads, budget awareness, graceful max-iterations degradation | 63 |
| `test_reflection.py` | Self-reflection critique, loop re-entry on low score, text-rewrite fallback when no budget, quality scoring, flag gating, graceful failure, DB persistence | 18 |
| `test_planner.py` | Plan parsing, provider error handling, summary generation | 13 |
| `test_memory.py` | Memory CRUD, keyword search, retrieval, export | 13 |
| `test_dreams.py` | Agent Dreams: dreamer core, pending review lifecycle, FIFO eviction, interval logic, planner context integration, DB migration | 21 |
| `test_scheduler.py` | Task scheduler: CRUD, lifecycle (pause/resume/delete), heap-based execution, inflight tracking, one-time and interval tasks, max_runs, pre-approval (once/recurring/approve_all), persistence roundtrip | 26 |
| `test_integration.py` | End-to-end legacy plan-and-execute path, provider switching, retry failed runs | 12 |

## Memory Export

Export all stored memory to human-readable JSON files:

```bash
python scripts/export_memory.py
# Output: exports/facts.json, exports/episodes.json, exports/summaries.json,
#         exports/strategies.json, exports/preferences.json, exports/audit_log.json
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ANTHROPIC_API_KEY not set` | Check your `.env` file exists and contains the key |
| `table runs has no column named iterations` | The DB was created before the ReAct update — restart the backend (auto-migration runs on startup) or delete `mini_openclaw.db` |
| `anthropic returned invalid JSON` | The LLM prefixed reasoning text before JSON — this is auto-handled; if persistent, check your API key and model |
| Agent keeps calling the same tool in a loop | Loop detection triggers after `REACT_DUPLICATE_CAP` identical calls (default: 3). Lower `REACT_MAX_ITERATIONS` in `.env` for tighter control |
| `Port 8000 already in use` | Kill the existing process or set `BACKEND_PORT` in `.env` |
| `Cannot connect to Ollama` | Ensure Ollama is running: `ollama serve`. Check `OLLAMA_BASE_URL` in `.env` |
| `Model 'X' not found` (Ollama) | Pull the model first: `ollama pull X` |
| Ollama response is slow | First call loads the model into memory — subsequent calls are faster. Try a smaller model like `phi3` |
| `CORS error in browser` | Ensure the backend is running on port 8000 |
| `No tools registered` | Check `apps/api/skills/` for import errors — run `python -c "from apps.api.skills.registry import SkillRegistry"` |
| `Database locked` | Close other server instances accessing the same `.db` file |
| `ModuleNotFoundError` | Ensure you installed deps: `pip install -r requirements.txt` |
| `sentence-transformers` download slow | First run downloads ~80 MB model; subsequent runs use cache. Set `HF_TOKEN` for faster downloads |
| Memory search only returns keyword matches | Check that `sentence-transformers` installed successfully; backend log should show "Embedding model loaded" on startup |
| Summaries tab is empty | Summaries auto-generate after every 5 completed runs. Run more tasks, or set `SUMMARY_INTERVAL=3` in `.env` for faster generation |
| Strategies/Preferences tabs are empty | Agent Dreams needs at least 3 episodes and triggers every `DREAM_INTERVAL` runs (default: 5). Click the ✨ Dream button manually, or run more tasks |
| Dream proposes no insights | Either not enough episodes (minimum 3), or the LLM didn't find patterns above the confidence threshold. Lower `DREAM_CONFIDENCE_THRESHOLD` in `.env` or run more diverse tasks |
| Frontend won't start | Ensure Node.js 18+ is installed: `node --version` |
| Sidebar graph is empty | The graph only appears during active runs or when you click the ↗ graph link on a completed message. For direct-answer runs (no tools used), no graph is shown |
| Graph link not visible on message | The graph link only appears on assistant messages that had a run with tool execution. Hover over the message to see the ↗ graph link |
| Vertex AI `PERMISSION_DENIED` | Enable the API: `gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT`. Wait 1-2 minutes for propagation |
| Vertex AI `DefaultCredentialsError` | Run `gcloud auth application-default login` and restart the backend |
| Vertex AI `API_KEY_SERVICE_BLOCKED` | You're using AI Studio mode but the API is blocked on your GCP project. Switch to Vertex AI mode: set `VERTEX_AI=true` with `GCP_PROJECT` in `.env` |
| Run appears stuck in chat | The SSE stream may have disconnected — click the input and send a new message, or refresh the page. Check that the backend is still running |
| Retry button doesn't appear | Retry only shows on assistant messages from failed or cancelled runs, and only when no other run is active |
| Self-check scores seem too harsh | Lower `REACT_REFLECT_QUALITY_THRESHOLD` (e.g. `0.5`) or disable with `REACT_SELF_REFLECT=false` |
| Runs are slow with self-reflection enabled | Self-reflection adds 1–2 extra LLM calls per run and may re-enter the loop. Disable it (`REACT_SELF_REFLECT=false`) for faster responses, or raise the threshold (`REACT_REFLECT_QUALITY_THRESHOLD=0.9`) so only poor answers trigger re-entry |
| Agent doesn't delegate when expected | The planner only delegates when it sees distinct independent sub-parts. Use explicit cues: "do these as independent sub-tasks", numbered lists, or "and also" joining unrelated tasks. Or explicitly say "delegate" |
| Delegation approval keeps appearing | Each child run is gated by a separate approval. This is by design — the user controls what work gets spawned. Set `DELEGATE_ENABLED=false` to disable delegation entirely |
| Child run appears stuck | The child has its own iteration budget (max 5 by default). Check if it's waiting for approval on a `write_file` or `run_shell_safe` call inside the child |
| Too many child runs spawning | Lower `DELEGATE_MAX_CHILDREN` in `.env` (default: 3). The planner also respects this limit and won't attempt more delegations than allowed |
| Child run not visible in UI | Expand the `delegate_task` observation row in the parent — the child run card with its observations renders inline. Child runs also appear separately in Run History |
| Scheduled task shows "Runs: 0" but is overdue | The scheduler loop may have crashed. Check `curl http://localhost:8000/api/scheduler/health` — if `loop_alive` is `false`, restart the backend. Also check the backend logs for `Scheduler loop error` |
| Scheduled task asks for approval but nobody sees it | Navigate to the **Scheduler** page — an approval card appears inline on the task card. The nav badge turns amber with **"!"** when approval is needed |
| Scheduled task was created but DB error appeared | Delete `mini_openclaw.db` and restart — the new schema includes the `pre_approved_tools` and `approve_all_runs` columns. Or just restart (auto-migration adds the missing columns) |

## Project Structure

```
mini-openclaw/
├── apps/api/              # FastAPI backend
│   ├── core/              #   Orchestrator, planner, policy, executor, audit, scheduler
│   ├── providers/         #   LLM provider abstraction (Anthropic, Gemini, Ollama)
│   ├── skills/            #   V1 tool implementations + registry + sub-agent delegation + scheduling
│   ├── memory/            #   Memory manager, hybrid retrieval, embeddings, vector store, dreamer
│   └── models/            #   Pydantic models (Run, ToolResult, ScheduledTask, ErrorKind, etc.)
├── apps/web/              # React + TypeScript frontend
│   └── src/components/    #   ChatPanel, PlanPreview, ExecutionGraph, ApprovalCard, ToolTrace, RunHistory, MemoryBrowser, SchedulerPage
├── tests/                 # pytest test suite (367 tests)
├── scripts/               # seed_demo.py (workspace + memory setup), export_memory.py
├── docs/                  # Architecture and design documentation
└── requirements.txt       # Python dependencies
```

## License

Course project — not licensed for production use.
