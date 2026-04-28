"""
Set up a demo workspace for evaluator use.

Creates:
- workspace/README.md (project description)
- workspace/src/main.py (simple Python file)
- workspace/src/utils.py (another Python file)
- workspace/docs/notes.md (markdown notes)
- workspace/data/sample.csv (small CSV)
- workspace/notes.txt (TODO list)
- workspace/config.json (project config)

Pre-populates memory with:
- Fact: "The demo workspace is at <path>"
- Fact: "This is a Python project using FastAPI"
- Fact: "The workspace contains README.md, notes.txt, config.json, src/, docs/, and data/"
- Episode: "Seed script created demo workspace with 7 files"

Usage:
    python scripts/seed_demo.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.config import get_settings
from apps.api.database import create_tables
from apps.api.memory.manager import MemoryManager


async def main() -> None:
    settings = get_settings()
    workspace = settings.resolved_workspace
    workspace.mkdir(parents=True, exist_ok=True)

    # ── Create demo files ─────────────────────────────────────────

    (workspace / "README.md").write_text(
        "# Demo Project\n\n"
        "This is a demo workspace for Mini-OpenClaw evaluation.\n\n"
        "## Features\n"
        "- Task routing via structured planner\n"
        "- Auditable memory system\n"
        "- Safe local execution with policy engine\n"
        "- Extensible tool registry\n\n"
        "## Getting Started\n"
        "Ask the agent to list files, read this README, or create new files.\n",
        encoding="utf-8",
    )

    (workspace / "notes.txt").write_text(
        "TODO: Review the architecture document\n"
        "TODO: Test memory search\n"
        "TODO: Run the shell safety tests\n"
        "DONE: Set up workspace\n"
        "DONE: Configure API key\n",
        encoding="utf-8",
    )

    (workspace / "config.json").write_text(
        '{\n  "project": "mini-openclaw",\n  "version": "0.1.0",\n  "debug": true\n}\n',
        encoding="utf-8",
    )

    src_dir = workspace / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "main.py").write_text(
        '"""Main application entry point."""\n\n'
        "def greet(name: str) -> str:\n"
        '    return f"Hello, {name}!"\n\n\n'
        'if __name__ == "__main__":\n'
        '    print(greet("Mini-OpenClaw"))\n',
        encoding="utf-8",
    )
    (src_dir / "utils.py").write_text(
        '"""Utility functions for the demo project."""\n\n'
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n\n\n"
        "def multiply(a: int, b: int) -> int:\n"
        "    return a * b\n",
        encoding="utf-8",
    )

    docs_dir = workspace / "docs"
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / "notes.md").write_text(
        "# Project Notes\n\n"
        "## Architecture Decisions\n"
        "- SQLite for persistence (lightweight, no server needed)\n"
        "- FastAPI for async backend\n"
        "- React + Vite for frontend\n\n"
        "## Open Questions\n"
        "- Should we add semantic search for memory retrieval?\n"
        "- What is the ideal approval timeout?\n",
        encoding="utf-8",
    )

    data_dir = workspace / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "sample.csv").write_text(
        "name,category,value\n"
        "alpha,A,10\n"
        "beta,B,20\n"
        "gamma,A,30\n"
        "delta,C,40\n"
        "epsilon,B,50\n",
        encoding="utf-8",
    )

    print(f"Created demo files in {workspace}")

    # ── Seed memory ───────────────────────────────────────────────

    await create_tables(settings.resolved_database)
    mm = MemoryManager(settings.resolved_database)

    await mm.store_fact(
        content=f"The demo workspace is at {workspace}",
        source="seed_demo",
        confidence=1.0,
    )
    await mm.store_fact(
        content="This is a Python project using FastAPI",
        source="seed_demo",
        confidence=1.0,
    )
    await mm.store_fact(
        content="The workspace contains README.md, notes.txt, config.json, src/, docs/, and data/",
        source="seed_demo",
        confidence=0.9,
    )
    await mm.store_episode(
        content="Seed script created demo workspace with 7 files across 4 directories.",
        summary="Demo workspace seeded",
        source="seed_demo",
        confidence=1.0,
    )

    items = await mm.list_items()
    print(f"Seeded memory with {len(items)} items")
    print("Demo setup complete!")


if __name__ == "__main__":
    asyncio.run(main())
