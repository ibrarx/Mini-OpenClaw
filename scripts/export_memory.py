"""
Dump all SQLite memory tables to human-readable JSON files.

Usage:
    python scripts/export_memory.py
"""
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.config import get_settings
from apps.api.memory.manager import MemoryManager


async def main() -> None:
    settings = get_settings()
    mm = MemoryManager(settings.resolved_database)

    export_dir = Path("exports")
    export_dir.mkdir(exist_ok=True)

    for mem_type in ("fact", "episode", "summary"):
        items = await mm.list_items(memory_type=mem_type, limit=10000)
        data = [i.model_dump() for i in items]
        out = export_dir / f"{mem_type}s.json"
        out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        print(f"Exported {len(data)} {mem_type}(s) to {out}")

    print("Export complete.")


if __name__ == "__main__":
    asyncio.run(main())
