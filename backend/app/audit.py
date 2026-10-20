from __future__ import annotations

import json
from typing import Any

from .db import Database, now_iso
from .events import EventBus
from .redaction import redact_obj


class AuditLog:
    def __init__(self, db: Database, bus: EventBus):
        self.db, self.bus = db, bus

    def record(self, actor: str, action: str, outcome: str, *, task_id: str | None = None, details: dict[str, Any] | None = None) -> None:
        safe = redact_obj(details or {})
        ts = now_iso()
        self.db.execute(
            "INSERT INTO audit_events(task_id, actor, action, outcome, timestamp, details_redacted_json) VALUES (?,?,?,?,?,?)",
            (task_id, actor, action, outcome, ts, json.dumps(safe)),
        )
        self.bus.publish("audit", {"task_id": task_id, "actor": actor, "action": action, "outcome": outcome})

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["details"] = json.loads(r.pop("details_redacted_json"))
        return rows
