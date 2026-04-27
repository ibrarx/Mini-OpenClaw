"""
Dump all SQLite memory tables to human-readable JSON files.

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

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.config import get_settings
from apps.api.database import get_connection


async def main() -> None:
    settings = get_settings()
    db_path = settings.resolved_database

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    export_dir = Path("exports")
    export_dir.mkdir(exist_ok=True)

    conn = await get_connection(db_path)
    try:
        # Export memory items by type
        for mem_type in ("fact", "episode", "summary"):
            rows = await conn.execute_fetchall(
                "SELECT * FROM memory_items WHERE memory_type = ? ORDER BY created_at DESC",
                (mem_type,),
            )
            items = [dict(r) for r in rows]
            path = export_dir / f"{mem_type}s.json"
            path.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")
            print(f"Exported {len(items)} {mem_type}s to {path}")

        # Export audit log
        rows = await conn.execute_fetchall(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 1000"
        )
        events = [dict(r) for r in rows]
        path = export_dir / "audit_log.json"
        path.write_text(json.dumps(events, indent=2, default=str), encoding="utf-8")
        print(f"Exported {len(events)} audit events to {path}")

    finally:
        await conn.close()

    print(f"\nAll exports saved to {export_dir.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
