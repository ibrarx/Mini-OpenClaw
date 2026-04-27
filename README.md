# Mini-OpenClaw

A lightweight local-first AI agent that converts natural-language requests into safe, auditable tool executions on your local machine. Built for the Applied Generative AI course at TU Wien.

## Features

- **Intent-to-tool routing**: Claude proposes structured JSON plans; code validates and executes
- **Auditable memory**: SQLite-backed with JSON export for human inspection
- **Extensible skills**: Manifest-driven tool registration with JSON schema validation
- **Safe execution**: Policy engine, command allowlists, and approval gates
- **Web UI**: Plans, approvals, tool traces, and memory browser

## Prerequisites

- Python 3.11 or later
- Node.js 18 or later
- An Anthropic API key

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/ibrarx/Mini-OpenClaw.git
cd Mini-OpenClaw
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set your ANTHROPIC_API_KEY
```

### 3. Install & run

**macOS / Linux:**

```bash
make install   # Install Python and Node dependencies
make dev       # Start backend (port 8000) and frontend (port 5173)
```

**Windows (CMD):**

```cmd
start.bat
```

**Windows (PowerShell):**

```powershell
.\start.ps1
```

### 4. Open the app

Navigate to [http://localhost:5173](http://localhost:5173) in your browser.

## Manual Setup (any OS)

If the startup scripts don't work for your environment:

```bash
# Terminal 1 — Backend (run from project root)
pip install -r requirements.txt
python -m uvicorn apps.api.main:app --reload --port 8000

# Terminal 2 — Frontend
cd apps/web
npm install
npm run dev
```

## Project Structure

```
mini-openclaw/
├── apps/api/          # FastAPI backend
├── apps/web/          # React + TypeScript frontend
├── tests/             # pytest test suite
├── scripts/           # Demo seeding and memory export
├── docs/              # Architecture documentation
└── requirements.txt   # Python dependencies
```

## Running Tests

```bash
make test
# or directly:
python -m pytest tests/ -v
```

## Memory Export

Export all memory to human-readable JSON files:

```bash
python scripts/export_memory.py
# Output: exports/facts.json, exports/episodes.json, etc.
```

## License

Course project — not licensed for production use.
