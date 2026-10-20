"""Persistent memory: SQLite + FTS5 keyword search + a pluggable local vector index, with provenance."""
from __future__ import annotations

import json
import logging
import re
import zlib
from array import array
from typing import Any, Protocol

from .db import Database, new_id, now_iso
from .redaction import contains_sensitive
from .settings_service import SettingsService

log = logging.getLogger(__name__)
CATEGORIES = ("working", "preference", "project", "procedural", "knowledge")
CATEGORY_TOGGLE = {"preference": "preferences", "project": "projects", "procedural": "workflows"}
MAX_LEN = 2000


class SensitiveContentError(ValueError):
    pass


class MemoryDisabled(RuntimeError):
    pass


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Dependency-free local embedder (signed feature hashing of words + character trigrams).
    It captures lexical/morphological similarity, NOT deep semantics; swap in a real embedder behind the same interface."""
    name = "local-hash-v1"
    dim = 256

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            feats = [(tok, 1.0)] + [(f"#{tok}#"[i:i + 3], 0.4) for i in range(max(1, len(tok) - 1))]
            for feat, w in feats:
                h = zlib.crc32(feat.encode())
                vec[h % self.dim] += w if (h >> 16) & 1 else -w
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm else vec


def _fts_query(q: str) -> str:
    toks = re.findall(r"\w+", q.lower())
    return " OR ".join(f'"{t}"*' for t in toks[:12])


class MemoryService:
    def __init__(self, db: Database, settings: SettingsService, embedder: Embedder | None = None):
        self.db, self.settings = db, settings
        self.embedder: Embedder = embedder or HashingEmbedder()

    # ---- helpers ------------------------------------------------------
    def _row(self, r: dict[str, Any]) -> dict[str, Any]:
        r = dict(r)
        r["user_approved"] = bool(r["user_approved"])
        r["provenance"] = {**json.loads(r.pop("provenance_json", "{}")), "source": r["source"], "created_at": r["created_at"],
                           "updated_at": r["updated_at"], "trust": "user_approved" if r["user_approved"] else "unreviewed_candidate"}
        return r

    def _check_text(self, content: str) -> str:
        content = (content or "").strip()
        if not content:
            raise ValueError("Memory content is empty.")
        if len(content) > MAX_LEN:
            raise ValueError(f"Memory content is too long (max {MAX_LEN} characters).")
        if contains_sensitive(content):
            raise SensitiveContentError("This looks like a secret or sensitive data (key, password, card or ID number). It was not saved.")
        return content

    def _index(self, memory_id: str, content: str) -> None:
        if not self.settings.get("memory")["semantic_index"]:
            return
        try:
            vec = array("f", self.embedder.embed(content))
            self.db.execute("INSERT OR REPLACE INTO memory_vectors(memory_id, embedder, dim, vector) VALUES (?,?,?,?)",
                            (memory_id, self.embedder.name, self.embedder.dim, vec.tobytes()))
        except Exception:
            log.warning("vector indexing failed; keyword search remains available", exc_info=True)

    # ---- CRUD ---------------------------------------------------------
    def status(self) -> dict[str, Any]:
        cnt = self.db.one("SELECT COUNT(*) c, SUM(user_approved=0) p FROM memories") or {}
        vec = self.db.one("SELECT COUNT(*) c FROM memory_vectors") or {}
        return {"enabled": self.settings.get("memory")["enabled"], "count": cnt.get("c", 0), "pending_review": cnt.get("p") or 0,
                "keyword_index": "fts5" if self.db.fts5 else "like-fallback",
                "semantic_index": {"enabled": self.settings.get("memory")["semantic_index"], "embedder": self.embedder.name, "indexed": vec.get("c", 0),
                                   "note": "Local approximate (lexical) similarity, not a neural embedding."}}

    def create(self, content: str, category: str, source: str, *, importance: float = 0.5, user_approved: bool = False,
               provenance: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = self.settings.get("memory")
        if not cfg["enabled"]:
            raise MemoryDisabled("Memory is turned off in your settings.")
        if category not in CATEGORIES:
            raise ValueError(f"Unknown memory category '{category}'.")
        toggle = CATEGORY_TOGGLE.get(category)
        if toggle and not cfg[toggle]:
            raise MemoryDisabled(f"Saving '{category}' memories is turned off in your settings.")
        content = self._check_text(content)
        mid, ts = new_id("mem_"), now_iso()
        self.db.execute(
            "INSERT INTO memories(id, category, content, source, created_at, updated_at, importance, user_approved, provenance_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (mid, category, content, source, ts, ts, max(0.0, min(1.0, importance)), 1 if user_approved else 0, json.dumps(provenance or {})))
        self._index(mid, content)
        return self.get(mid)  # type: ignore[return-value]

    def get(self, memory_id: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM memories WHERE id=?", (memory_id,))
        return self._row(r) if r else None

    def list(self, *, category: str | None = None, approved: bool | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM memories WHERE 1=1", []
        if category:
            sql += " AND category=?"; params.append(category)
        if approved is not None:
            sql += " AND user_approved=?"; params.append(1 if approved else 0)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        return [self._row(r) for r in self.db.query(sql, (*params, limit, offset))]

    def update(self, memory_id: str, **fields: Any) -> dict[str, Any] | None:
        cur = self.get(memory_id)
        if not cur:
            return None
        sets, params = [], []
        if fields.get("content") is not None:
            sets.append("content=?"); params.append(self._check_text(fields["content"]))
        if fields.get("category") is not None:
            if fields["category"] not in CATEGORIES:
                raise ValueError("Unknown memory category.")
            sets.append("category=?"); params.append(fields["category"])
        if fields.get("importance") is not None:
            sets.append("importance=?"); params.append(max(0.0, min(1.0, float(fields["importance"]))))
        if fields.get("user_approved") is not None:
            sets.append("user_approved=?"); params.append(1 if fields["user_approved"] else 0)
        if not sets:
            return cur
        sets.append("updated_at=?"); params.append(now_iso())
        self.db.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id=?", (*params, memory_id))
        if fields.get("content") is not None:
            self._index(memory_id, fields["content"])
        return self.get(memory_id)

    def delete(self, memory_id: str) -> bool:
        return self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,)).rowcount > 0

    def clear(self) -> int:
        n = self.db.execute("DELETE FROM memories").rowcount
        self.db.execute("DELETE FROM memory_vectors")
        return n

    # ---- retrieval ----------------------------------------------------
    def search(self, query: str, limit: int = 8, *, include_unapproved: bool = False) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        approved_sql = "" if include_unapproved else " AND m.user_approved=1"
        ranks: dict[str, dict[str, Any]] = {}

        def add(mid: str, how: str, rank: int) -> None:
            e = ranks.setdefault(mid, {"score": 0.0, "match": []})
            e["score"] += 1.0 / (60 + rank)
            e["match"].append(how)

        fts_q = _fts_query(query)
        if fts_q:
            if self.db.fts5:
                try:
                    rows = self.db.query(
                        "SELECT m.id FROM memories_fts f JOIN memories m ON m.rowid=f.rowid WHERE memories_fts MATCH ?" + approved_sql + " ORDER BY rank LIMIT ?",
                        (fts_q, limit * 3))
                except Exception:
                    log.warning("FTS query failed; using LIKE fallback", exc_info=True)
                    rows = self._like(query, approved_sql, limit * 3)
            else:
                rows = self._like(query, approved_sql, limit * 3)
            for i, r in enumerate(rows):
                add(r["id"], "keyword", i)

        if self.settings.get("memory")["semantic_index"]:
            qv = array("f", self.embedder.embed(query))
            scored: list[tuple[float, str]] = []
            for r in self.db.query("SELECT v.memory_id, v.vector FROM memory_vectors v JOIN memories m ON m.id=v.memory_id WHERE v.embedder=?" + approved_sql, (self.embedder.name,)):
                mv = array("f"); mv.frombytes(r["vector"])
                sim = sum(a * b for a, b in zip(qv, mv))
                if sim >= 0.3:
                    scored.append((sim, r["memory_id"]))
            for i, (_, mid) in enumerate(sorted(scored, reverse=True)[: limit * 3]):
                add(mid, "semantic", i)

        out = []
        for mid, e in ranks.items():
            m = self.get(mid)
            if m:
                m["score"] = round(e["score"] * (0.8 + 0.4 * m["importance"]), 6)
                m["match"] = e["match"]
                out.append(m)
        return sorted(out, key=lambda x: x["score"], reverse=True)[:limit]

    def _like(self, query: str, approved_sql: str, limit: int) -> list[dict[str, Any]]:
        toks = re.findall(r"\w+", query.lower())[:8]
        if not toks:
            return []
        cond = " OR ".join("LOWER(m.content) LIKE ?" for _ in toks)
        score = " + ".join("(LOWER(m.content) LIKE ?)" for _ in toks)
        likes = [f"%{t}%" for t in toks]
        return self.db.query(f"SELECT m.id FROM memories m WHERE ({cond}){approved_sql} ORDER BY ({score}) DESC LIMIT ?", (*likes, *likes, limit))
