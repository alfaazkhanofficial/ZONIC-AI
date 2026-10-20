from __future__ import annotations

from app.db import now_iso
from conftest import run_task, say


async def test_agent_history_works_with_messages_without_rowid(env):
    """Existing user databases may declare messages WITHOUT ROWID."""
    db = env.svc.db
    db.execute("DROP TABLE messages")
    db.execute(
        """CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        ) WITHOUT ROWID"""
    )
    db.execute("CREATE INDEX idx_messages_conv ON messages(conversation_id, created_at)")

    # Include two messages with equal timestamps to exercise deterministic ordering.
    ts = now_iso()
    env.svc.chat.ensure(None, "prior message")
    cid = db.one("SELECT id FROM conversations ORDER BY created_at DESC LIMIT 1")["id"]
    db.execute(
        "INSERT INTO messages(id, conversation_id, role, content, created_at, metadata_json) VALUES (?,?,?,?,?,?)",
        ("msg_a", cid, "user", "older user message", ts, "{}"),
    )
    db.execute(
        "INSERT INTO messages(id, conversation_id, role, content, created_at, metadata_json) VALUES (?,?,?,?,?,?)",
        ("msg_b", cid, "assistant", "older assistant message", ts, "{}"),
    )

    # Directly verify chronology/tie-breaking, then exercise the full agent path.
    history = env.svc.chat.messages(cid, limit=20)
    assert [m["id"] for m in history] == ["msg_a", "msg_b"]

    env.provider.script = [say("I can read the conversation history and respond.")]
    submitted = await env.svc.agent.submit("continue this conversation", cid)
    task = await env.svc.tasks.wait(submitted["task_id"])
    assert task["status"] == "completed", task["result"]
    assert task["result"]["final"].startswith("I can read the conversation history")
