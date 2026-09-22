from __future__ import annotations

import json
import uuid

from .db import Database, utcnow


class ProjectStore:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, name: str, state: dict | None = None) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("project name cannot be empty")
        now = utcnow()
        payload = json.dumps(state or {}, ensure_ascii=False, sort_keys=True)
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO projects(name, status, state_json, updated_at)
                   VALUES (?, 'active', ?, ?)
                   ON CONFLICT(name) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at""",
                (name, payload, now),
            )
            row = con.execute("SELECT id, name, status, state_json, updated_at FROM projects WHERE name = ?", (name,)).fetchone()
        self.db.add_event("project.upserted", {"name": name})
        return dict(row)

    def list(self) -> list[dict]:
        with self.db.connect() as con:
            rows = con.execute("SELECT id, name, status, state_json, updated_at FROM projects ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def add_task(self, project_name: str, title: str, details: str = "") -> dict:
        project = self.upsert(project_name)
        task_id = uuid.uuid4().hex
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO tasks(id, project_id, title, details, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'todo', ?, ?)",
                (task_id, project["id"], title.strip(), details, now, now),
            )
        self.db.add_event("task.created", {"task_id": task_id, "project": project_name})
        return {"id": task_id, "project": project_name, "title": title.strip(), "details": details, "status": "todo"}

    def tasks(self, project_name: str) -> list[dict]:
        with self.db.connect() as con:
            rows = con.execute(
                """SELECT t.id, t.title, t.details, t.status, t.created_at, t.updated_at
                   FROM tasks t JOIN projects p ON p.id=t.project_id
                   WHERE p.name=? ORDER BY t.created_at""",
                (project_name,),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_task_status(self, task_id: str, status: str) -> None:
        if status not in {"todo", "doing", "blocked", "done", "cancelled"}:
            raise ValueError("invalid task status")
        with self.db.connect() as con:
            cur = con.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, utcnow(), task_id))
            if cur.rowcount != 1:
                raise KeyError(task_id)
        self.db.add_event("task.status", {"task_id": task_id, "status": status})
