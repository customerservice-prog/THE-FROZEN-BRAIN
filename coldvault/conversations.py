from __future__ import annotations

import uuid
from dataclasses import dataclass

from .db import Database, utcnow


@dataclass
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str


class ConversationStore:
    def __init__(self, db: Database):
        self.db = db

    def ensure(self, conversation_id: str = "default", title: str = "ColdVault") -> str:
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, title, now, now),
            )
        return conversation_id

    def create(self, title: str = "New conversation") -> str:
        conversation_id = uuid.uuid4().hex
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, title.strip() or "New conversation", now, now),
            )
        self.db.add_event("conversation.created", {"conversation_id": conversation_id})
        return conversation_id

    def append(self, conversation_id: str, role: str, content: str, metadata_json: str = "{}") -> int:
        self.ensure(conversation_id)
        now = utcnow()
        with self.db.connect() as con:
            cur = con.execute(
                "INSERT INTO messages(conversation_id, ts, role, content, metadata_json) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, now, role, content, metadata_json),
            )
            con.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
            return int(cur.lastrowid)

    def history(self, conversation_id: str, limit: int = 40) -> list[dict]:
        self.ensure(conversation_id)
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT id, ts, role, content, metadata_json FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
                (conversation_id, max(1, min(limit, 200))),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def list(self, limit: int = 50) -> list[dict]:
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(r) for r in rows]
