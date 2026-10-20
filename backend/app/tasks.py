"""Task manager: persisted state machine, event log, cancellation, bounded concurrency."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

from .audit import AuditLog
from .db import Database, new_id, now_iso
from .events import EventBus
from .redaction import redact, redact_obj
from .settings_service import SettingsService
from .types import TERMINAL_STATES, TRANSITIONS, TaskState

log = logging.getLogger(__name__)
Runner = Callable[[dict[str, Any], asyncio.Event], Awaitable[None]]


class TaskManager:
    def __init__(self, db: Database, bus: EventBus, audit: AuditLog, settings: SettingsService):
        self.db, self.bus, self.audit, self.settings = db, bus, audit, settings
        self._cancel: dict[str, asyncio.Event] = {}
        self._runners: dict[str, asyncio.Task[None]] = {}
        self._running = 0
        # A previous process can't still be running these.
        for t in self.db.query("SELECT id FROM tasks WHERE status NOT IN ('completed','failed','cancelled')"):
            self.db.execute("UPDATE tasks SET status='failed', updated_at=?, result_json=? WHERE id=?",
                            (now_iso(), json.dumps({"error": "Interrupted: the app was closed or restarted while this task was running."}), t["id"]))

    # ---- queries ------------------------------------------------------
    def _row(self, r: dict[str, Any]) -> dict[str, Any]:
        r = dict(r)
        r["cancel_requested"] = bool(r["cancel_requested"])
        r["result"] = json.loads(r.pop("result_json") or "{}")
        return r

    def get(self, task_id: str, with_events: bool = False) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not r:
            return None
        t = self._row(r)
        if with_events:
            t["events"] = self.events(task_id)
        return t

    def list(self, status: str | None = None, limit: int = 50, active_only: bool = False) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM tasks", []
        if status:
            sql += " WHERE status=?"; params.append(status)
        elif active_only:
            sql += " WHERE status NOT IN ('completed','failed','cancelled')"
        sql += " ORDER BY created_at DESC LIMIT ?"
        return [self._row(r) for r in self.db.query(sql, (*params, limit))]

    def events(self, task_id: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM task_events WHERE task_id=? ORDER BY id LIMIT ?", (task_id, limit))
        for r in rows:
            r["data"] = json.loads(r.pop("data_json"))
        return rows

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM task_events ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["data"] = json.loads(r.pop("data_json"))
        return rows

    # ---- mutations ----------------------------------------------------
    def create(self, goal: str, conversation_id: str | None) -> dict[str, Any]:
        tid, ts = new_id("task_"), now_iso()
        self.db.execute("INSERT INTO tasks(id, conversation_id, goal, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                        (tid, conversation_id, redact(goal)[:2000], TaskState.QUEUED.value, ts, ts))
        self._cancel[tid] = asyncio.Event()
        self.add_event(tid, "created", "Task created")
        self.bus.publish("task_state", {"task_id": tid, "state": TaskState.QUEUED.value, "message": "Task created"})
        return self.get(tid)  # type: ignore[return-value]

    def add_event(self, task_id: str, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        ts = now_iso()
        cur = self.db.execute("INSERT INTO task_events(task_id, kind, message, timestamp, data_json) VALUES (?,?,?,?,?)",
                              (task_id, kind, redact(message)[:1000], ts, json.dumps(redact_obj(data or {}))))
        self.bus.publish("task_event", {"task_id": task_id, "event_id": cur.lastrowid, "kind": kind, "message": redact(message)[:1000], "data": data or {}, "timestamp": ts})

    def set_state(self, task_id: str, state: TaskState, message: str | None = None, result: dict[str, Any] | None = None) -> bool:
        t = self.get(task_id)
        if not t:
            return False
        cur = TaskState(t["status"])
        if cur in TERMINAL_STATES or (state != cur and state not in TRANSITIONS[cur]):
            log.info("ignored task transition %s -> %s", cur.value, state.value, extra={"task_id": task_id})
            return False
        merged = {**t["result"], **(redact_obj(result) if result else {})}
        self.db.execute("UPDATE tasks SET status=?, updated_at=?, result_json=? WHERE id=?", (state.value, now_iso(), json.dumps(merged), task_id))
        if message or state != cur:
            self.add_event(task_id, "state", message or f"State: {state.value}", {"state": state.value})
        self.bus.publish("task_state", {"task_id": task_id, "state": state.value, "message": message or ""})
        return True

    def cancel_event(self, task_id: str) -> asyncio.Event:
        return self._cancel.setdefault(task_id, asyncio.Event())

    def request_cancel(self, task_id: str) -> dict[str, Any]:
        t = self.get(task_id)
        if not t:
            return {"accepted": False, "reason": "not_found"}
        if TaskState(t["status"]) in TERMINAL_STATES:
            return {"accepted": False, "reason": "already_finished", "state": t["status"]}
        self.db.execute("UPDATE tasks SET cancel_requested=1, updated_at=? WHERE id=?", (now_iso(), task_id))
        self.cancel_event(task_id).set()
        self.add_event(task_id, "cancel_requested", "Cancellation requested")
        self.bus.publish("task_state", {"task_id": task_id, "state": t["status"], "message": "Cancellation requested", "cancel_requested": True})
        return {"accepted": True, "state": t["status"]}

    # ---- execution ----------------------------------------------------
    def start(self, task: dict[str, Any], runner: Runner) -> None:
        tid = task["id"]

        async def _go() -> None:
            cancel = self.cancel_event(tid)
            try:
                while self._running >= self.settings.get("limits")["max_concurrent_tasks"] and not cancel.is_set():
                    await asyncio.sleep(0.05)
                self._running += 1
                try:
                    await runner(task, cancel)
                finally:
                    self._running -= 1
            except asyncio.CancelledError:
                self.set_state(tid, TaskState.CANCELLED, "Stopped (app shutting down)")
                raise
            except Exception as exc:
                log.exception("task runner crashed", extra={"task_id": tid})
                self.set_state(tid, TaskState.FAILED, f"Internal error: {type(exc).__name__}", {"error": f"Internal error: {type(exc).__name__}"})
            finally:
                cur = self.get(tid)
                if cur and TaskState(cur["status"]) not in TERMINAL_STATES:
                    self.set_state(tid, TaskState.FAILED, "Task ended without a result", {"error": "Task ended without a result."})
                self._runners.pop(tid, None)

        self._runners[tid] = asyncio.get_running_loop().create_task(_go())

    async def wait(self, task_id: str, timeout: float = 30.0) -> dict[str, Any]:
        r = self._runners.get(task_id)
        if r:
            await asyncio.wait_for(asyncio.shield(r), timeout)
        return self.get(task_id)  # type: ignore[return-value]

    def active_runner_count(self) -> int:
        return len(self._runners)

    async def shutdown(self) -> None:
        for ev in self._cancel.values():
            ev.set()
        runners = list(self._runners.values())
        if runners:
            done, pending = await asyncio.wait(runners, timeout=5)
            for p in pending:
                p.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    @staticmethod
    def elapsed_s(task: dict[str, Any]) -> float:
        a, b = datetime.fromisoformat(task["created_at"]), datetime.fromisoformat(task["updated_at"])
        return max(0.0, (b - a).total_seconds())
