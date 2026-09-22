from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .checkpoint_auth import ALGORITHM, load_checkpoint_key, seal_checkpoint, verify_checkpoint_seal
from .db import Database, utcnow


@dataclass
class CognitiveState:
    active_project: str | None = None
    objective: str | None = None
    subgoals: list[str] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    next_action: str | None = None
    pending_actions: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    commitments: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=utcnow)

    @classmethod
    def from_dict(cls, data: dict) -> "CognitiveState":
        allowed = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


class ContinuityEngine:
    def __init__(self, db: Database, checkpoint_dir: Path):
        self.db = db
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.state = self.restore_latest()

    def _event_cursor(self) -> int:
        with self.db.connect() as con:
            row = con.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM events").fetchone()
        return int(row["max_id"])

    def _replay(self, state: CognitiveState, after_event_id: int = 0) -> CognitiveState:
        with self.db.connect() as con:
            rows = con.execute(
                """SELECT id, payload_json FROM events
                   WHERE kind = 'continuity.updated' AND id > ?
                   ORDER BY id""",
                (int(after_event_id),),
            ).fetchall()
        replayed = 0
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                continue
            changes = payload.get("changes")
            if not isinstance(changes, dict):
                # Older ColdVault builds only recorded field names and cannot
                # reconstruct values. They are intentionally skipped.
                continue
            for key, value in changes.items():
                if key in CognitiveState.__dataclass_fields__ and key != "updated_at":
                    setattr(state, key, value)
            updated_at = payload.get("updated_at")
            if isinstance(updated_at, str):
                state.updated_at = updated_at
            replayed += 1
        if replayed:
            self.db.add_event(
                "continuity.replayed",
                {"after_event_id": int(after_event_id), "updates": replayed},
            )
        return state

    def update(self, **changes) -> CognitiveState:
        for key, value in changes.items():
            if key not in CognitiveState.__dataclass_fields__ or key == "updated_at":
                raise ValueError(f"unknown or protected cognitive-state field: {key}")
            setattr(self.state, key, value)
        self.state.updated_at = utcnow()
        self.db.add_event(
            "continuity.updated",
            {
                "fields": sorted(changes),
                "changes": changes,
                "updated_at": self.state.updated_at,
            },
        )
        return self.state

    def checkpoint(self, reason: str = "manual") -> dict:
        # Capture the event cursor BEFORE writing the checkpoint so updates
        # after this exact point can be replayed after an unexpected crash.
        event_cursor = self._event_cursor()
        data = asdict(self.state)
        data["checkpointed_at"] = utcnow()
        data["_event_cursor"] = event_cursor
        canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        key = load_checkpoint_key()
        auth = None
        if key:
            auth = {"algorithm": ALGORITHM, "tag": seal_checkpoint(canonical, key)}
        envelope = {"version": 2, "checksum": digest, "state": data, "authentication": auth}
        path = self.checkpoint_dir / f"checkpoint-{data['checkpointed_at'].replace(':', '-')}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        with self.db.connect() as con:
            cur = con.execute(
                "INSERT INTO checkpoints(ts, reason, state_json, checksum) VALUES (?, ?, ?, ?)",
                (data["checkpointed_at"], reason, canonical, digest),
            )
            checkpoint_id = int(cur.lastrowid)
            if auth:
                con.execute(
                    "INSERT INTO checkpoint_seals(checkpoint_id, algorithm, tag) VALUES (?, ?, ?)",
                    (checkpoint_id, auth["algorithm"], auth["tag"]),
                )
        self.db.add_event(
            "checkpoint.created",
            {
                "checkpoint_id": checkpoint_id,
                "reason": reason,
                "checksum": digest,
                "event_cursor": event_cursor,
            },
        )
        return {
            "id": checkpoint_id,
            "path": str(path),
            "checksum": digest,
            "event_cursor": event_cursor,
            "authenticated": bool(auth),
            "authentication_algorithm": auth["algorithm"] if auth else None,
        }

    def restore_latest(self) -> CognitiveState:
        with self.db.connect() as con:
            row = con.execute(
                """SELECT c.id, c.state_json, c.checksum, s.algorithm, s.tag
                   FROM checkpoints c
                   LEFT JOIN checkpoint_seals s ON s.checkpoint_id = c.id
                   ORDER BY c.id DESC LIMIT 1"""
            ).fetchone()
        if not row:
            # No checkpoint yet: replay any modern continuity events from a
            # clean state so early work can still survive a process crash.
            return self._replay(CognitiveState(), 0)

        canonical = row["state_json"]
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if digest != row["checksum"]:
            raise RuntimeError("latest cognitive checkpoint failed checksum validation")

        if row["tag"] is not None:
            key = load_checkpoint_key()
            if not key:
                raise RuntimeError(
                    "latest cognitive checkpoint is authenticated but no checkpoint key is available"
                )
            if row["algorithm"] != ALGORITHM or not verify_checkpoint_seal(canonical, row["tag"], key):
                raise RuntimeError("latest cognitive checkpoint failed authentication validation")

        data = json.loads(canonical)
        cursor = int(data.get("_event_cursor", 0) or 0)
        state = CognitiveState.from_dict(data)
        return self._replay(state, cursor)

    def snapshot(self) -> dict:
        return asdict(self.state)
