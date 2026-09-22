from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

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
        self.state = self.restore_latest() or CognitiveState()

    def update(self, **changes) -> CognitiveState:
        for key, value in changes.items():
            if key not in CognitiveState.__dataclass_fields__:
                raise ValueError(f"unknown cognitive-state field: {key}")
            setattr(self.state, key, value)
        self.state.updated_at = utcnow()
        self.db.add_event("continuity.updated", {"fields": sorted(changes)})
        return self.state

    def checkpoint(self, reason: str = "manual") -> dict:
        data = asdict(self.state)
        data["checkpointed_at"] = utcnow()
        canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        envelope = {"version": 1, "checksum": digest, "state": data}
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
        self.db.add_event("checkpoint.created", {"checkpoint_id": checkpoint_id, "reason": reason, "checksum": digest})
        return {"id": checkpoint_id, "path": str(path), "checksum": digest}

    def restore_latest(self) -> CognitiveState | None:
        with self.db.connect() as con:
            row = con.execute(
                "SELECT state_json, checksum FROM checkpoints ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        canonical = row["state_json"]
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if digest != row["checksum"]:
            raise RuntimeError("latest cognitive checkpoint failed checksum validation")
        return CognitiveState.from_dict(json.loads(canonical))

    def snapshot(self) -> dict:
        return asdict(self.state)
