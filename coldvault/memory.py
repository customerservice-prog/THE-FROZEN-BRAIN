from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .db import Database, utcnow


_WORD = re.compile(r"[A-Za-z0-9_'-]+")


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD.finditer(text) if len(m.group(0)) > 1}


@dataclass
class Memory:
    id: int
    ts: str
    kind: str
    content: str
    source: str | None
    confidence: float
    tags: list[str]


class MemoryStore:
    VALID_KINDS = {"episodic", "semantic", "procedural", "prospective", "preference", "relationship"}

    def __init__(self, db: Database):
        self.db = db

    def remember(self, content: str, *, kind: str = "semantic", source: str | None = None,
                 confidence: float = 1.0, tags: list[str] | None = None) -> int:
        content = content.strip()
        if not content:
            raise ValueError("memory content cannot be empty")
        if kind not in self.VALID_KINDS:
            raise ValueError(f"invalid memory kind: {kind}")
        confidence = max(0.0, min(1.0, float(confidence)))
        with self.db.connect() as con:
            cur = con.execute(
                "INSERT INTO memories(ts, kind, content, source, confidence, tags_json) VALUES (?, ?, ?, ?, ?, ?)",
                (utcnow(), kind, content, source, confidence, json.dumps(tags or [], ensure_ascii=False)),
            )
            memory_id = int(cur.lastrowid)
        self.db.add_event("memory.created", {"memory_id": memory_id, "kind": kind, "source": source})
        return memory_id

    def search(self, query: str, limit: int = 8) -> list[Memory]:
        q = _tokens(query)
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT id, ts, kind, content, source, confidence, tags_json FROM memories ORDER BY id DESC LIMIT 1000"
            ).fetchall()
        scored = []
        for r in rows:
            hay = _tokens(r["content"] + " " + (r["source"] or "") + " " + r["tags_json"])
            overlap = len(q & hay)
            if not q or overlap:
                score = overlap + float(r["confidence"]) * 0.25
                scored.append((score, r))
        scored.sort(key=lambda item: (item[0], item[1]["id"]), reverse=True)
        result = []
        for _, r in scored[: max(1, min(limit, 50))]:
            result.append(Memory(
                id=r["id"], ts=r["ts"], kind=r["kind"], content=r["content"], source=r["source"],
                confidence=float(r["confidence"]), tags=json.loads(r["tags_json"]),
            ))
        return result
