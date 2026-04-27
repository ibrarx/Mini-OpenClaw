"""
Populate a demo workspace and memory store for evaluation.

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

    # Create sample files
    (workspace / "README.md").write_text(
        "# Demo Project\n\nThis is a demo workspace for Mini-OpenClaw evaluation.\n\n"
        "## Features\n- Task routing\n- Memory system\n- Safe execution\n",
        encoding="utf-8")
    (workspace / "notes.txt").write_text(
        "TODO: Review the architecture document\n"
        "TODO: Test memory search\n"
        "DONE: Set up workspace\n", encoding="utf-8")
    (workspace / "config.json").write_text(
        '{"project": "mini-openclaw", "version": "0.1.0", "debug": true}',
        encoding="utf-8")

    src_dir = workspace / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "main.py").write_text(
        "# Main application entry point\nprint(\"Hello from Mini-OpenClaw!\")\n",
        encoding="utf-8")

    print(f"Created demo files in {workspace}")

    # Seed memory
    await create_tables(settings.resolved_database)
    mm = MemoryManager(settings.resolved_database)
    await mm.store_fact("The demo workspace contains a README, notes, config, and src/main.py",
                         source="seed_demo", confidence=0.9)
    await mm.store_fact("The project is called Mini-OpenClaw",
                         source="seed_demo", confidence=1.0)
    print("Seeded memory with demo facts")
    print("Demo setup complete!")


if __name__ == "__main__":
    asyncio.run(main())
