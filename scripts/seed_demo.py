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
    db_path = settings.resolved_database

    # Create workspace
    workspace.mkdir(parents=True, exist_ok=True)
    print(f"Workspace: {workspace}")

    # Create DB tables
    await create_tables(db_path)
    print(f"Database: {db_path}")

    # Seed workspace files
    readme = workspace / "README.md"
    if not readme.exists():
        readme.write_text("# Demo Workspace\n\nThis is a demo workspace for Mini-OpenClaw.\n\n"
                          "## Files\n- notes.txt: Project notes\n- data/: Data directory\n",
                          encoding="utf-8")
        print("Created README.md")

    notes = workspace / "notes.txt"
    if not notes.exists():
        notes.write_text("Project notes:\n- TODO: Set up testing framework\n"
                         "- TODO: Review security model\n- DONE: Initial architecture\n",
                         encoding="utf-8")
        print("Created notes.txt")

    data_dir = workspace / "data"
    data_dir.mkdir(exist_ok=True)
    sample = data_dir / "sample.csv"
    if not sample.exists():
        sample.write_text("name,value,category\nalpha,42,A\nbeta,17,B\ngamma,99,A\n",
                          encoding="utf-8")
        print("Created data/sample.csv")

    # Seed memory
    mm = MemoryManager(db_path)
    await mm.store_fact(content="Demo workspace is a test project for evaluation.",
                        source="seed_demo", confidence=0.9)
    await mm.store_fact(content="User prefers concise responses.",
                        source="seed_demo", confidence=0.7)
    print("Seeded 2 memory facts")

    print("\nDemo setup complete! Start the server with: make dev")


if __name__ == "__main__":
    asyncio.run(main())
