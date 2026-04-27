"""core/audit — Append-only audit event logger."""
import json, logging, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import aiosqlite
from apps.api.database import get_connection

logger = logging.getLogger(__name__)

class AuditLogger:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def log(self, event_type: str, *, run_id: str | None = None,
                  step_id: str | None = None, data: dict[str, Any] | None = None) -> str:
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(data or {}, default=str)
        conn = await get_connection(self._db_path)
        try:
            await conn.execute(
                "INSERT INTO audit_events (id, event_type, run_id, step_id, data, created_at) VALUES (?,?,?,?,?,?)",
                (event_id, event_type, run_id, step_id, payload, now))
            await conn.commit()
        finally:
            await conn.close()
        logger.debug("Audit: %s run=%s step=%s", event_type, run_id, step_id)
        return event_id
