"""SQLite access: schema/migrations, FTS5 (with LIKE fallback), small thread-safe wrapper."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX idx_messages_conv ON messages(conversation_id, created_at);
    CREATE TABLE tasks (id TEXT PRIMARY KEY, conversation_id TEXT, goal TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0, result_json TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX idx_tasks_status ON tasks(status, created_at);
    CREATE TABLE task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        kind TEXT NOT NULL, message TEXT NOT NULL, timestamp TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX idx_task_events_task ON task_events(task_id, id);
    CREATE TABLE memories (id TEXT PRIMARY KEY, category TEXT NOT NULL, content TEXT NOT NULL, source TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, importance REAL NOT NULL DEFAULT 0.5,
        user_approved INTEGER NOT NULL DEFAULT 0, provenance_json TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE memory_vectors (memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
        embedder TEXT NOT NULL, dim INTEGER NOT NULL, vector BLOB NOT NULL);
    CREATE TABLE tool_records (name TEXT PRIMARY KEY, version TEXT NOT NULL, description TEXT NOT NULL, schema_json TEXT NOT NULL,
        permission TEXT, enabled INTEGER NOT NULL DEFAULT 1, validation_state TEXT NOT NULL DEFAULT 'builtin');
    CREATE TABLE approvals (id TEXT PRIMARY KEY, task_id TEXT, kind TEXT NOT NULL DEFAULT 'action', action_summary TEXT NOT NULL,
        risk_level TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT, payload_json TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE audit_events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, actor TEXT NOT NULL, action TEXT NOT NULL,
        outcome TEXT NOT NULL, timestamp TEXT NOT NULL, details_redacted_json TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX idx_audit_ts ON audit_events(timestamp);
    CREATE TABLE skills (name TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL, definition_json TEXT NOT NULL,
        validation_json TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT, created_by TEXT NOT NULL,
        PRIMARY KEY (name, version));
    """),
]


class Database:
    def __init__(self, path: Path | str, *, force_no_fts: bool = False):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA foreign_keys=ON")
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self.fts5 = False
        self._migrate()
        if not force_no_fts:
            self.fts5 = self._setup_fts()

    def _migrate(self) -> None:
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            done = {r[0] for r in self._conn.execute("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version in done:
                    continue
                self._conn.execute("BEGIN")
                try:
                    for stmt in filter(None, (s.strip() for s in sql.split(";"))):
                        self._conn.execute(stmt)
                    self._conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, now_iso()))
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise

    def _setup_fts(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, category, content='memories', content_rowid='rowid')")
                self._conn.execute("""CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content, category) VALUES (new.rowid, new.content, new.category); END""")
                self._conn.execute("""CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, category) VALUES ('delete', old.rowid, old.content, old.category); END""")
                self._conn.execute("""CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, category) VALUES ('delete', old.rowid, old.content, old.category);
                    INSERT INTO memories_fts(rowid, content, category) VALUES (new.rowid, new.content, new.category); END""")
            return True
        except sqlite3.OperationalError:
            return False

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def integrity_ok(self) -> bool:
        row = self.one("PRAGMA quick_check")
        return bool(row) and list(row.values())[0] == "ok"

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- tiny helpers -------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value_json FROM settings WHERE key=?", (key,))
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key, value_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (key, json.dumps(value), now_iso()),
        )
