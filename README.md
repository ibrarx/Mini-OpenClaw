# Mini-OpenClaw

A lightweight local-first AI agent that converts natural-language requests into safe, auditable tool executions on your local machine.

**Course:** Applied Generative AI — TU Wien
**Group:** _[Group number]_
**Members:** _[Member names]_

---

## Overview

Mini-OpenClaw takes plain-language instructions from a user, routes them through a structured planner (Claude), validates every proposed action against a security policy engine, and executes approved steps using a registry of local tools — all within an auditable, inspectable pipeline. Key features include intent-to-tool routing via structured JSON plans, human-readable memory backed by SQLite with JSON export, manifest-driven tool extensibility (add a tool without touching the core), and a multi-layer security model with approval gates for risky operations.

## Prerequisites

- **Python 3.11+** — [python.org/downloads](https://www.python.org/downloads/)
- **Node.js 18+** and npm — [nodejs.org](https://nodejs.org/)
- **Anthropic API key** — [console.anthropic.com](https://console.anthropic.com/)

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

1. **"List files in the workspace"** — safe tool, auto-executes
2. **"Read the README file"** — reads and displays file content
3. **"Create a file called notes.txt with a summary of the project"** — triggers approval flow
4. **"Search for TODO in all files"** — grep-like search across workspace
5. **"Remember that I prefer dark mode"** — stores a fact in memory, visible in Memory Browser

## Architecture

Mini-OpenClaw follows a run-centric architecture: every user request becomes a **run** with discrete steps, each validated and logged. The conversation orchestrator coordinates the pipeline: the **planner** (Claude) proposes a structured JSON plan, the **policy engine** classifies each step as safe / approval-required / forbidden, the **executor** runs approved steps through the **skill registry**, and the **memory manager** persists useful context. An append-only **audit logger** records every decision for inspection. See [docs/architecture.md](docs/architecture.md) for the full design.

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
4. Restart the server — the skill registry auto-discovers it

No changes to the orchestrator, policy engine, or executor code are required.

## Configuration

All settings are read from the `.env` file (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key | _(required)_ |
| `WORKSPACE_ROOT` | Directory the agent operates in | `./workspace` |
| `DATABASE_PATH` | SQLite database file path | `./mini_openclaw.db` |
| `ANTHROPIC_MODEL` | Claude model to use | `claude-sonnet-4-20250514` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `BACKEND_PORT` | Backend server port | `8000` |

## Running Tests

```bash
# macOS / Linux
make test

# Any OS
python -m pytest tests/ -v
```

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
| `Port 8000 already in use` | Kill the existing process or set `BACKEND_PORT` in `.env` |
| `CORS error in browser` | Ensure the backend is running on port 8000 |
| `No tools registered` | Check `apps/api/skills/` for import errors — run `python -c "from apps.api.skills.registry import SkillRegistry"` |
| `Database locked` | Close other server instances accessing the same `.db` file |
| `ModuleNotFoundError` | Ensure you installed deps: `pip install -r requirements.txt` |
| Frontend won't start | Ensure Node.js 18+ is installed: `node --version` |

## Project Structure

```
mini-openclaw/
├── apps/api/          # FastAPI backend (orchestrator, planner, policy, skills, memory)
├── apps/web/          # React + TypeScript frontend (chat, approvals, memory browser)
├── tests/             # pytest test suite
├── scripts/           # Demo seeding and memory export
├── docs/              # Architecture and design documentation
└── requirements.txt   # Python dependencies
```

## License

Course project — not licensed for production use.
