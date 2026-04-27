"""
Dump all SQLite memory tables to human-readable JSON files.

Usage:
    python scripts/export_memory.py
    python scripts/export_memory.py --db path/to/mini_openclaw.db

Output:
    exports/facts.json
    exports/episodes.json
    exports/summaries.json
    exports/audit_log.json
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def export_memory(db_path: Path, output_dir: Path) -> None:
    """Read all memory items and audit events from SQLite and write JSON files.

    Args:
        db_path: Path to the SQLite database file.
        output_dir: Directory to write JSON files into.
    """
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Export memory items grouped by type
    memory_types = {
        "fact": "facts.json",
        "episode": "episodes.json",
        "summary": "summaries.json",
    }

    for mem_type, filename in memory_types.items():
        rows = conn.execute(
            "SELECT * FROM memory_items WHERE memory_type = ? ORDER BY created_at DESC",
            (mem_type,),
        ).fetchall()

        items = [dict(row) for row in rows]
        out_path = output_dir / filename
        out_path.write_text(json.dumps(items, indent=2, ensure_ascii=False))
        print(f"Exported {len(items)} {mem_type}(s) -> {out_path}")

    # Export audit events
    rows = conn.execute(
        "SELECT * FROM audit_events ORDER BY created_at DESC"
    ).fetchall()

    events = []
    for row in rows:
        event = dict(row)
        # Parse JSON data field
        if event.get("data"):
            try:
                event["data"] = json.loads(event["data"])
            except (json.JSONDecodeError, TypeError):
                pass
        events.append(event)

    audit_path = output_dir / "audit_log.json"
    audit_path.write_text(json.dumps(events, indent=2, ensure_ascii=False))
    print(f"Exported {len(events)} audit event(s) -> {audit_path}")

    conn.close()
    print(f"\nAll exports complete. Output directory: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Mini-OpenClaw memory to JSON files")
    parser.add_argument(
        "--db",
        type=str,
        default="mini_openclaw.db",
        help="Path to SQLite database (default: mini_openclaw.db)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="exports",
        help="Output directory (default: exports/)",
    )
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    output_dir = Path(args.output).resolve()

    export_memory(db_path, output_dir)


if __name__ == "__main__":
    main()
