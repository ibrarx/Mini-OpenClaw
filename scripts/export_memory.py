"""
Dump all SQLite memory tables and audit log to human-readable JSON files.

Usage:
    python scripts/export_memory.py

Output:
    exports/facts.json
    exports/episodes.json
    exports/summaries.json
    exports/audit_log.json
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.config import get_settings
from apps.api.database import get_connection
from apps.api.memory.manager import MemoryManager


def export_memory(db_path: Path, export_dir: Path) -> None:
    """Synchronous wrapper for the async export logic."""
    asyncio.run(_export_async(db_path, export_dir))


async def _export_async(db_path: Path, export_dir: Path) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)
    mm = MemoryManager(db_path)

    for mem_type in ("fact", "episode", "summary"):
        items = await mm.list_items(memory_type=mem_type, limit=10000)
        data = [i.model_dump() for i in items]
        out = export_dir / f"{mem_type}s.json"
        out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        print(f"Exported {len(data)} {mem_type}(s) to {out}")

    # Export audit log
    conn = await get_connection(db_path)
    try:
        rows = await conn.execute_fetchall(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 10000"
        )
        events = [dict(row) for row in rows]
        out = export_dir / "audit_log.json"
        out.write_text(json.dumps(events, indent=2, default=str), encoding="utf-8")
        print(f"Exported {len(events)} audit event(s) to {out}")
    finally:
        await conn.close()

    print("Export complete.")


async def main() -> None:
    settings = get_settings()
    export_dir = Path("exports")
    await _export_async(settings.resolved_database, export_dir)


if __name__ == "__main__":
    asyncio.run(main())
