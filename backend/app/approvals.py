"""Human-in-the-loop approvals. The backend is the only authority; the UI just records the decision."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from .audit import AuditLog
from .db import Database, new_id, now_iso
from .events import EventBus
from .redaction import redact, redact_obj
from .types import Risk


class ApprovalManager:
    def __init__(self, db: Database, bus: EventBus, audit: AuditLog):
        self.db, self.bus, self.audit = db, bus, audit
        self._futures: dict[str, asyncio.Future[str]] = {}
        # Anything pending from a previous process can no longer be awaited.
        self.db.execute("UPDATE approvals SET state='expired', decided_at=? WHERE state='pending'", (now_iso(),))

    async def request(self, *, task_id: str | None, summary: str, risk: Risk, kind: str = "action", payload: dict[str, Any] | None = None, wait: bool = True) -> str:
        aid = new_id("apr_")
        self.db.execute(
            "INSERT INTO approvals(id, task_id, kind, action_summary, risk_level, state, created_at, payload_json) VALUES (?,?,?,?,?,?,?,?)",
            (aid, task_id, kind, redact(summary), risk.value, "pending", now_iso(), json.dumps(redact_obj(payload or {}))),
        )
        if wait:
            self._futures[aid] = asyncio.get_running_loop().create_future()
        self.audit.record("agent", f"approval_requested:{kind}", "pending", task_id=task_id, details={"approval_id": aid, "summary": summary, "risk": risk.value})
        self.bus.publish("approval_requested", {"approval_id": aid, "task_id": task_id, "kind": kind, "summary": redact(summary), "risk": risk.value})
        return aid

    async def wait(self, approval_id: str, cancel: asyncio.Event, timeout: float = 900.0) -> str:
        fut = self._futures.get(approval_id)
        if fut is None:
            return "expired"
        canceller = asyncio.ensure_future(cancel.wait())
        try:
            done, _ = await asyncio.wait({fut, canceller}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if fut in done:
                return fut.result()
            if canceller in done:
                self._finish(approval_id, "cancelled")
                return "cancelled"
            self._finish(approval_id, "expired")
            return "expired"
        finally:
            canceller.cancel()
            self._futures.pop(approval_id, None)

    def _finish(self, approval_id: str, state: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not row or row["state"] != "pending":
            return None
        self.db.execute("UPDATE approvals SET state=?, decided_at=? WHERE id=?", (state, now_iso(), approval_id))
        self.audit.record("user" if state in ("approved", "denied") else "system", "approval_" + state, state, task_id=row["task_id"], details={"approval_id": approval_id})
        self.bus.publish("approval_resolved", {"approval_id": approval_id, "task_id": row["task_id"], "state": state})
        return {**row, "state": state}

    def decide(self, approval_id: str, approve: bool) -> dict[str, Any] | None:
        state = "approved" if approve else "denied"
        row = self._finish(approval_id, state)
        if row is None:
            return None
        fut = self._futures.get(approval_id)
        if fut and not fut.done():
            fut.set_result(state)
        return row

    def pending(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM approvals WHERE state='pending' ORDER BY created_at")
        for r in rows:
            r["payload"] = json.loads(r.pop("payload_json"))
        return rows

    def get(self, approval_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if row:
            row["payload"] = json.loads(row.pop("payload_json"))
        return row
