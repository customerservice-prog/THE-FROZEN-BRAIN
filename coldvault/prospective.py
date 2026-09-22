from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .db import Database, utcnow


def _utc(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_due(value: datetime | str) -> str:
    return _utc(value).isoformat()


class ProspectiveMemory:
    STATUSES = {"pending", "done", "cancelled"}

    def __init__(self, db: Database):
        self.db = db

    def create(self, content: str, due_at: datetime | str, *, source: str = "user") -> str:
        content = content.strip()
        if not content:
            raise ValueError("prospective memory content cannot be empty")
        reminder_id = uuid.uuid4().hex
        due = normalize_due(due_at)
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO prospective_actions
                   (id, created_at, due_at, content, source, status, completed_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', NULL)""",
                (reminder_id, now, due, content, source),
            )
        self.db.add_event(
            "prospective.created",
            {"id": reminder_id, "due_at": due, "source": source, "content": content},
        )
        return reminder_id

    def list(self, status: str | None = "pending", limit: int = 100) -> list[dict]:
        if status is not None and status not in self.STATUSES:
            raise ValueError(f"invalid prospective status: {status}")
        with self.db.connect() as con:
            if status is None:
                rows = con.execute(
                    """SELECT id, created_at, due_at, content, source, status, completed_at
                       FROM prospective_actions ORDER BY due_at LIMIT ?""",
                    (max(1, min(limit, 1000)),),
                ).fetchall()
            else:
                rows = con.execute(
                    """SELECT id, created_at, due_at, content, source, status, completed_at
                       FROM prospective_actions WHERE status = ? ORDER BY due_at LIMIT ?""",
                    (status, max(1, min(limit, 1000))),
                ).fetchall()
        return [dict(row) for row in rows]

    def due(self, now: datetime | str | None = None, limit: int = 50) -> list[dict]:
        cutoff = _utc(now).isoformat()
        with self.db.connect() as con:
            rows = con.execute(
                """SELECT id, created_at, due_at, content, source, status, completed_at
                   FROM prospective_actions
                   WHERE status = 'pending' AND due_at <= ?
                   ORDER BY due_at LIMIT ?""",
                (cutoff, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_status(self, reminder_id: str, status: str) -> None:
        if status not in {"done", "cancelled", "pending"}:
            raise ValueError(f"invalid prospective status: {status}")
        completed_at = utcnow() if status in {"done", "cancelled"} else None
        with self.db.connect() as con:
            cur = con.execute(
                "UPDATE prospective_actions SET status = ?, completed_at = ? WHERE id = ?",
                (status, completed_at, reminder_id),
            )
            if cur.rowcount != 1:
                raise KeyError(reminder_id)
        self.db.add_event("prospective.status", {"id": reminder_id, "status": status})

    def summary_for_prompt(self, now: datetime | str | None = None, upcoming_limit: int = 8) -> str:
        due = self.due(now, limit=upcoming_limit)
        if due:
            return "\n".join(
                f"- DUE {item['due_at']}: {item['content']} (source={item['source']})"
                for item in due
            )
        pending = self.list("pending", limit=upcoming_limit)
        if not pending:
            return "- none"
        return "\n".join(
            f"- UPCOMING {item['due_at']}: {item['content']} (source={item['source']})"
            for item in pending
        )
