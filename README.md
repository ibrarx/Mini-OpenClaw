# Mini-OpenClaw

A lightweight local-first AI agent that converts natural-language requests into safe, auditable tool executions on your local machine.

**Course:** Applied Generative AI — TU Wien
**Group:** _[Group number]_
**Members:** _[Member names]_

---

## Overview

Mini-OpenClaw takes plain-language instructions from a user, routes them through a structured planner (Claude or Gemini), validates every proposed action against a security policy engine, and executes approved steps using a registry of local tools — all within an auditable, inspectable pipeline.

The agent uses a **ReAct (Reason → Act → Observe) loop** as its default execution model: the LLM thinks about what to do next, executes one tool, observes the result, and decides the next action — adapting in real time to errors, policy denials, and user rejections. A legacy plan-and-execute mode is available for comparison.

Key features:

- **ReAct loop** with iterative reasoning and real-time adaptation to failures
- **Real-time SSE streaming** — run status, plans, and approvals pushed to the frontend instantly via Server-Sent Events (no polling)
- **User-friendly status announcements** — the agent narrates what it's doing in plain language ("Let me search your files…") instead of showing raw tool names, with full tool traceability preserved in expandable details
- **Hybrid semantic memory** — 70% vector similarity + 30% keyword matching, powered by local sentence-transformers embeddings (no API cost)
- **Three memory layers** — durable facts, episodic task history, and auto-generated conversation summaries
- **Saga compensation** — reject a step and all previous write operations are automatically rolled back
- **Error classification** — transient errors are retried with backoff, permanent errors go straight to the LLM, side-effect errors are surfaced to the user
- **LLM-provider-agnostic** — swap Claude for Gemini (or add your own) without touching core code
- **Manifest-driven tool extensibility** — add a tool without rewriting the core agent loop
- **Multi-layer security** — policy engine, command allowlists, and approval gates for risky operations
- **Full audit trail** — every decision logged in an append-only audit table

## Prerequisites

- **Python 3.11+** — [python.org/downloads](https://www.python.org/downloads/)
- **Node.js 18+** and npm — [nodejs.org](https://nodejs.org/)
- **An API key from either**:
  - **Anthropic** (default) — [console.anthropic.com](https://console.anthropic.com/), or
  - **Google Gemini** — [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

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

### Saga compensation — rollback on rejection
12. **"Create files called a.txt, b.txt, and c.txt with some content"** — approve the first two, then **reject** the third. The first two files are automatically deleted (saga rollback). Check the workspace to verify they're gone.

### Error classification
13. **"Read /etc/passwd"** — policy denial (path outside workspace), LLM sees the denial and explains why it can't help

### Auto-generated summaries
14. Run 5 different tasks (steps 1–5 above). After the 5th completes, check **Memory → Summaries** — a conversation summary should appear, auto-generated by the LLM from your recent interactions.

## Execution Modes

### ReAct loop (default)

The agent iterates: **Think → Act → Observe**, up to a configurable maximum number of iterations. Each iteration, the LLM decides whether to call a tool or give a final answer based on all previous observations.

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

## Switching LLM providers

Mini-OpenClaw is LLM-provider-agnostic. The planner talks to an abstract
`LLMProvider` interface (see [`docs/provider-abstraction.md`](docs/provider-abstraction.md));
concrete providers are plug-in modules. Two are shipped today: **Anthropic
Claude** (default) and **Google Gemini**.

To switch, edit `.env`:

```dotenv
# Use Anthropic (default)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=claude-sonnet-4-20250514

# OR use Gemini
LLM_PROVIDER=gemini
GEMINI_API_KEY=AI...
# GEMINI_MODEL=gemini-2.5-flash
```

Restart the backend. Verify with:

```bash
curl http://localhost:8000/api/health
```

You should see `"llm_provider": "gemini"` (or `"anthropic"`) and
`"api_key_configured": true`.

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

## Memory System

Mini-OpenClaw has a three-layer memory system with hybrid semantic search, designed so the agent remembers user preferences, learns from past tasks, and builds up context over time.

### Memory types

| Type | What it stores | Created by | Example |
|------|---------------|------------|---------|
| **Fact** | Durable user or workspace preferences | User via `remember_fact` tool | "User prefers VS Code", "Project uses PostgreSQL" |
| **Episode** | Record of a completed task with tools used and outcome | System, automatically after each run | "User asked to list files → list_files → found 12 items" |
| **Summary** | Compressed overview of recent interactions | System, auto-generated every N runs via LLM | "The user is working on a thesis about NLP. Prefers Python." |

Facts persist until manually deleted. Episodes accumulate indefinitely. Summaries are auto-generated every `SUMMARY_INTERVAL` completed runs (default: 5) and the system keeps the `MAX_SUMMARIES` most recent (default: 3).

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

## Relevant Past Context
- [2 hours ago] Listed files in workspace — found 12 Python files
- [yesterday] User asked to summarize README.md — created summary.txt

## Conversation Summary
User is working on a thesis project involving NLP. Prefers concise responses.
```

This context is injected into the LLM system prompt with explicit instructions to use it, so the agent doesn't ask questions it already knows the answer to.

## Available Tools

| Tool | Description | Risk Level | Approval Required |
|------|-------------|------------|-------------------|
| `list_files` | List files and directories in the workspace | Safe | No |
| `read_file` | Read a text file from the workspace | Safe | No |
| `write_file` | Create, overwrite, or append to a file | Medium | Yes |
| `search_in_files` | Search for patterns across text files | Safe | No |
| `run_shell_safe` | Execute allowlisted commands (pwd, ls, find, cat, grep) | Medium–High | Yes |
| `remember_fact` | Store a durable fact in memory | Safe | No |
| `search_memory` | Query stored facts, episodes, and summaries | Safe | No |

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
| `GEMINI_API_KEY` | Your Google Gemini API key | _(required if using Gemini)_ |
| `LLM_PROVIDER` | Which LLM backend to use | `anthropic` |
| `WORKSPACE_ROOT` | Directory the agent operates in | `./workspace` |
| `DATABASE_PATH` | SQLite database file path | `./mini_openclaw.db` |
| `ANTHROPIC_MODEL` | Claude model to use | `claude-sonnet-4-20250514` |
| `GEMINI_MODEL` | Gemini model to use | `gemini-2.5-flash` |
| `USE_REACT` | Use iterative ReAct loop (`true`) or legacy plan-and-execute (`false`) | `true` |
| `REACT_MAX_ITERATIONS` | Maximum think→act→observe iterations per run | `10` |
| `REACT_DUPLICATE_CAP` | Block after N consecutive identical tool+args calls (minimum: 2) | `3` |
| `SUMMARY_INTERVAL` | Auto-generate a summary every N completed runs (0 = disable) | `5` |
| `MAX_SUMMARIES` | Number of summaries to keep (oldest pruned) | `3` |
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
| `test_memory_semantic.py` | Hybrid search, embedding, vector store, planner wiring, summaries | 44 |
| `test_policy.py` | Path validation, shell blocking, injection detection, risk classification | 38 |
| `test_providers.py` | Anthropic/Gemini provider translation, factory, JSON extraction | 37 |
| `test_tools.py` | Each V1 tool in isolation | 33 |
| `test_react.py` | ReAct loop, saga compensation, error classification, loop detection, approval flow | 30 |
| `test_planner.py` | Plan parsing, provider error handling, summary generation | 13 |
| `test_memory.py` | Memory CRUD, keyword search, retrieval, export | 13 |
| `test_integration.py` | End-to-end legacy plan-and-execute path, provider switching | 8 |

## Memory Export

Export all stored memory to human-readable JSON files:

```bash
python scripts/export_memory.py
# Output: exports/facts.json, exports/episodes.json, exports/summaries.json, exports/audit_log.json
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ANTHROPIC_API_KEY not set` | Check your `.env` file exists and contains the key |
| `table runs has no column named iterations` | The DB was created before the ReAct update — restart the backend (auto-migration runs on startup) or delete `mini_openclaw.db` |
| `anthropic returned invalid JSON` | The LLM prefixed reasoning text before JSON — this is auto-handled; if persistent, check your API key and model |
| Agent keeps calling the same tool in a loop | Loop detection triggers after `REACT_DUPLICATE_CAP` identical calls (default: 3). Lower `REACT_MAX_ITERATIONS` in `.env` for tighter control |
| `Port 8000 already in use` | Kill the existing process or set `BACKEND_PORT` in `.env` |
| `CORS error in browser` | Ensure the backend is running on port 8000 |
| `No tools registered` | Check `apps/api/skills/` for import errors — run `python -c "from apps.api.skills.registry import SkillRegistry"` |
| `Database locked` | Close other server instances accessing the same `.db` file |
| `ModuleNotFoundError` | Ensure you installed deps: `pip install -r requirements.txt` |
| `sentence-transformers` download slow | First run downloads ~80 MB model; subsequent runs use cache. Set `HF_TOKEN` for faster downloads |
| Memory search only returns keyword matches | Check that `sentence-transformers` installed successfully; backend log should show "Embedding model loaded" on startup |
| Summaries tab is empty | Summaries auto-generate after every 5 completed runs. Run more tasks, or set `SUMMARY_INTERVAL=3` in `.env` for faster generation |
| Frontend won't start | Ensure Node.js 18+ is installed: `node --version` |
| Run appears stuck in chat | The SSE stream may have disconnected — click the input and send a new message, or refresh the page. Check that the backend is still running |

## Project Structure

```
mini-openclaw/
├── apps/api/              # FastAPI backend
│   ├── core/              #   Orchestrator, planner, policy, executor, audit
│   ├── providers/         #   LLM provider abstraction (Anthropic, Gemini)
│   ├── skills/            #   V1 tool implementations + registry
│   ├── memory/            #   Memory manager, hybrid retrieval, embeddings, vector store
│   └── models/            #   Pydantic models (Run, ToolResult, ErrorKind, etc.)
├── apps/web/              # React + TypeScript frontend
│   └── src/components/    #   ChatPanel, PlanPreview, ApprovalCard, ToolTrace, RunHistory, MemoryBrowser
├── tests/                 # pytest test suite (216 tests)
├── scripts/               # Demo seeding and memory export
├── docs/                  # Architecture and design documentation
└── requirements.txt       # Python dependencies
```

## License

Course project — not licensed for production use.
