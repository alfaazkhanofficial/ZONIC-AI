"""Conversation/message persistence. Honors the 'conversation history' privacy choice."""
from __future__ import annotations

import json
from typing import Any

from .db import Database, new_id, now_iso
from .redaction import redact
from .settings_service import SettingsService


class ChatStore:
    def __init__(self, db: Database, settings: SettingsService):
        self.db, self.settings = db, settings
        self._ephemeral: dict[str, list[dict[str, Any]]] = {}  # used only when history saving is off

    def _persist(self) -> bool:
        return bool(self.settings.get("memory")["conversation_history"])

    def ensure(self, conversation_id: str | None, first_message: str) -> str:
        if conversation_id and (self.db.one("SELECT id FROM conversations WHERE id=?", (conversation_id,)) or conversation_id in self._ephemeral):
            return conversation_id
        cid = new_id("conv_")
        title = redact(first_message.strip().splitlines()[0] if first_message.strip() else "Conversation")[:60]
        if self._persist():
            ts = now_iso()
            self.db.execute("INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?,?,?,?)", (cid, title, ts, ts))
        else:
            self._ephemeral[cid] = []
        return cid

    def add(self, conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        msg = {"id": new_id("msg_"), "conversation_id": conversation_id, "role": role, "content": redact(content), "created_at": now_iso(), "metadata": metadata or {}}
        if conversation_id in self._ephemeral:
            self._ephemeral[conversation_id].append(msg)
        else:
            self.db.execute("INSERT INTO messages(id, conversation_id, role, content, created_at, metadata_json) VALUES (?,?,?,?,?,?)",
                            (msg["id"], conversation_id, role, msg["content"], msg["created_at"], json.dumps(msg["metadata"])))
            self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (msg["created_at"], conversation_id))
        return msg

    def messages(self, conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
        if conversation_id in self._ephemeral:
            return self._ephemeral[conversation_id][-limit:]
        # `id` is the table's declared primary key. Unlike SQLite's implicit `rowid`,
        # it also works when an existing database stores this table `WITHOUT ROWID`.
        # Use the same deterministic tie-breaker on both sides of the limit so the
        # newest N messages are returned in chronological order.
        rows = self.db.query(
            "SELECT * FROM (SELECT * FROM messages WHERE conversation_id=? "
            "ORDER BY created_at DESC, id DESC LIMIT ?) ORDER BY created_at, id",
            (conversation_id, limit),
        )
        for r in rows:
            r["metadata"] = json.loads(r.pop("metadata_json"))
        return rows

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,))

    def delete(self, conversation_id: str) -> bool:
        self._ephemeral.pop(conversation_id, None)
        return self.db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,)).rowcount > 0

    def clear_all(self) -> None:
        self._ephemeral.clear()
        self.db.execute("DELETE FROM conversations")
