from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from .db import Database, utcnow
from .tool_protocol import ToolRegistry


@dataclass
class ToolJob:
    id: str
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    tool_name: str
    arguments: dict
    status: str
    result: object | None
    error: str | None
    attempt: int
    parent_job_id: str | None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "attempt": self.attempt,
            "parent_job_id": self.parent_job_id,
        }


class ToolJobStore:
    TERMINAL = {"succeeded", "failed", "cancelled"}
    RETRYABLE = {"failed", "interrupted", "cancelled"}

    def __init__(self, db: Database, tools: ToolRegistry):
        self.db = db
        self.tools = tools
        self.recover_interrupted()

    def _decode(self, row) -> ToolJob:
        try:
            result = json.loads(row["result_json"]) if row["result_json"] else None
        except json.JSONDecodeError:
            result = {"raw": row["result_json"]}
        try:
            arguments = json.loads(row["args_json"])
        except json.JSONDecodeError:
            arguments = {}
        return ToolJob(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            tool_name=row["tool_name"],
            arguments=arguments,
            status=row["status"],
            result=result,
            error=row["error"],
            attempt=int(row["attempt"]),
            parent_job_id=row["parent_job_id"],
        )

    def recover_interrupted(self) -> int:
        now = utcnow()
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT id, tool_name FROM tool_jobs WHERE status = 'running'"
            ).fetchall()
            if rows:
                con.executemany(
                    """UPDATE tool_jobs
                       SET status = 'interrupted', updated_at = ?, finished_at = ?,
                           error = COALESCE(error, 'process stopped while tool job was running')
                       WHERE id = ?""",
                    [(now, now, row["id"]) for row in rows],
                )
        for row in rows:
            self.db.add_event(
                "tool_job.interrupted",
                {"job_id": row["id"], "tool": row["tool_name"]},
            )
        return len(rows)

    def create(self, tool_name: str, arguments: dict, *, parent_job_id: str | None = None, attempt: int = 1) -> str:
        if not isinstance(arguments, dict):
            raise ValueError("tool job arguments must be an object")
        job_id = uuid.uuid4().hex
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO tool_jobs
                   (id, created_at, updated_at, started_at, finished_at, tool_name,
                    args_json, status, result_json, error, attempt, parent_job_id)
                   VALUES (?, ?, ?, NULL, NULL, ?, ?, 'queued', NULL, NULL, ?, ?)""",
                (
                    job_id,
                    now,
                    now,
                    tool_name,
                    json.dumps(arguments, ensure_ascii=False, sort_keys=True),
                    int(attempt),
                    parent_job_id,
                ),
            )
        self.db.add_event(
            "tool_job.queued",
            {
                "job_id": job_id,
                "tool": tool_name,
                "attempt": int(attempt),
                "parent_job_id": parent_job_id,
            },
        )
        return job_id

    def get(self, job_id: str) -> ToolJob:
        with self.db.connect() as con:
            row = con.execute(
                """SELECT id, created_at, updated_at, started_at, finished_at, tool_name,
                          args_json, status, result_json, error, attempt, parent_job_id
                   FROM tool_jobs WHERE id = ?""",
                (job_id,),
            ).fetchone()
        if not row:
            raise KeyError(job_id)
        return self._decode(row)

    def list(self, status: str | None = None, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        with self.db.connect() as con:
            if status:
                rows = con.execute(
                    """SELECT id, created_at, updated_at, started_at, finished_at, tool_name,
                              args_json, status, result_json, error, attempt, parent_job_id
                       FROM tool_jobs WHERE status = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (status, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    """SELECT id, created_at, updated_at, started_at, finished_at, tool_name,
                              args_json, status, result_json, error, attempt, parent_job_id
                       FROM tool_jobs ORDER BY created_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return [self._decode(row).as_dict() for row in rows]

    def run(self, tool_name: str, arguments: dict, *, parent_job_id: str | None = None, attempt: int = 1) -> ToolJob:
        job_id = self.create(tool_name, arguments, parent_job_id=parent_job_id, attempt=attempt)
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "UPDATE tool_jobs SET status='running', started_at=?, updated_at=? WHERE id=?",
                (now, now, job_id),
            )
        self.db.add_event("tool_job.started", {"job_id": job_id, "tool": tool_name})
        try:
            result = self.tools.run(tool_name, arguments)
        except BaseException as exc:
            finished = utcnow()
            with self.db.connect() as con:
                con.execute(
                    """UPDATE tool_jobs
                       SET status='failed', updated_at=?, finished_at=?, error=?
                       WHERE id=?""",
                    (finished, finished, f"{type(exc).__name__}: {exc}", job_id),
                )
            self.db.add_event(
                "tool_job.failed",
                {"job_id": job_id, "tool": tool_name, "error": f"{type(exc).__name__}: {exc}"},
            )
            raise

        finished = utcnow()
        try:
            encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except TypeError:
            encoded = json.dumps({"repr": repr(result)}, ensure_ascii=False)
        with self.db.connect() as con:
            con.execute(
                """UPDATE tool_jobs
                   SET status='succeeded', updated_at=?, finished_at=?, result_json=?, error=NULL
                   WHERE id=?""",
                (finished, finished, encoded, job_id),
            )
        self.db.add_event("tool_job.succeeded", {"job_id": job_id, "tool": tool_name})
        return self.get(job_id)

    def retry(self, job_id: str) -> ToolJob:
        original = self.get(job_id)
        if original.status not in self.RETRYABLE:
            raise ValueError(f"job {job_id} is {original.status!r} and is not retryable")
        return self.run(
            original.tool_name,
            original.arguments,
            parent_job_id=original.id,
            attempt=original.attempt + 1,
        )

    def cancel(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.status not in {"queued", "interrupted"}:
            raise ValueError(f"only queued or interrupted jobs can be cancelled; current status is {job.status}")
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "UPDATE tool_jobs SET status='cancelled', updated_at=?, finished_at=? WHERE id=?",
                (now, now, job_id),
            )
        self.db.add_event("tool_job.cancelled", {"job_id": job_id, "tool": job.tool_name})
