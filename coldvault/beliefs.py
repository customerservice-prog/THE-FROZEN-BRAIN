from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass

from .db import Database, utcnow

_WORD = re.compile(r"[A-Za-z0-9_'-]+")


@dataclass
class Belief:
    id: str
    created_at: str
    updated_at: str
    claim: str
    classification: str
    confidence: float
    status: str
    source: str | None
    evidence: list[dict]

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "claim": self.claim,
            "classification": self.classification,
            "confidence": self.confidence,
            "status": self.status,
            "source": self.source,
            "evidence": self.evidence,
        }


class BeliefStore:
    CLASSIFICATIONS = {
        "fact", "observation", "user_report", "documented",
        "inference", "hypothesis", "assumption", "disputed", "unknown",
    }
    STATUSES = {"active", "supported", "contradicted", "resolved", "retracted"}
    EVIDENCE_KINDS = {"supports", "contradicts", "context"}

    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        claim: str,
        *,
        classification: str = "hypothesis",
        confidence: float = 0.5,
        source: str | None = None,
        status: str = "active",
    ) -> str:
        claim = claim.strip()
        if not claim:
            raise ValueError("belief claim cannot be empty")
        if classification not in self.CLASSIFICATIONS:
            raise ValueError(f"invalid belief classification: {classification}")
        if status not in self.STATUSES:
            raise ValueError(f"invalid belief status: {status}")
        confidence = max(0.0, min(1.0, float(confidence)))
        belief_id = uuid.uuid4().hex
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO beliefs(id, created_at, updated_at, claim, classification, confidence, status, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (belief_id, now, now, claim, classification, confidence, status, source),
            )
        self.db.add_event("belief.created", {
            "belief_id": belief_id, "classification": classification,
            "confidence": confidence, "source": source,
        })
        return belief_id

    def add_evidence(
        self,
        belief_id: str,
        content: str,
        *,
        kind: str = "supports",
        source: str | None = None,
        confidence: float = 1.0,
    ) -> int:
        if kind not in self.EVIDENCE_KINDS:
            raise ValueError(f"invalid evidence kind: {kind}")
        content = content.strip()
        if not content:
            raise ValueError("evidence content cannot be empty")
        confidence = max(0.0, min(1.0, float(confidence)))
        now = utcnow()
        with self.db.connect() as con:
            exists = con.execute("SELECT 1 FROM beliefs WHERE id = ?", (belief_id,)).fetchone()
            if not exists:
                raise KeyError(belief_id)
            cur = con.execute(
                """INSERT INTO belief_evidence(belief_id, created_at, kind, content, source, confidence)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (belief_id, now, kind, content, source, confidence),
            )
            con.execute("UPDATE beliefs SET updated_at = ? WHERE id = ?", (now, belief_id))
            evidence_id = int(cur.lastrowid)
        self.db.add_event("belief.evidence", {
            "belief_id": belief_id, "evidence_id": evidence_id, "kind": kind, "source": source,
        })
        return evidence_id

    def set_status(self, belief_id: str, status: str, *, confidence: float | None = None) -> None:
        if status not in self.STATUSES:
            raise ValueError(f"invalid belief status: {status}")
        now = utcnow()
        with self.db.connect() as con:
            if confidence is None:
                cur = con.execute(
                    "UPDATE beliefs SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, belief_id),
                )
            else:
                bounded = max(0.0, min(1.0, float(confidence)))
                cur = con.execute(
                    "UPDATE beliefs SET status = ?, confidence = ?, updated_at = ? WHERE id = ?",
                    (status, bounded, now, belief_id),
                )
            if cur.rowcount != 1:
                raise KeyError(belief_id)
        self.db.add_event("belief.status", {"belief_id": belief_id, "status": status})

    def get(self, belief_id: str) -> Belief:
        with self.db.connect() as con:
            row = con.execute(
                """SELECT id, created_at, updated_at, claim, classification, confidence, status, source
                   FROM beliefs WHERE id = ?""",
                (belief_id,),
            ).fetchone()
            if not row:
                raise KeyError(belief_id)
            evidence_rows = con.execute(
                """SELECT id, created_at, kind, content, source, confidence
                   FROM belief_evidence WHERE belief_id = ? ORDER BY id""",
                (belief_id,),
            ).fetchall()
        return Belief(
            id=row["id"], created_at=row["created_at"], updated_at=row["updated_at"],
            claim=row["claim"], classification=row["classification"],
            confidence=float(row["confidence"]), status=row["status"], source=row["source"],
            evidence=[dict(x) for x in evidence_rows],
        )

    def search(self, query: str, limit: int = 8) -> list[Belief]:
        words = {m.group(0).lower() for m in _WORD.finditer(query) if len(m.group(0)) > 1}
        with self.db.connect() as con:
            rows = con.execute(
                """SELECT id, claim, confidence FROM beliefs
                   WHERE status NOT IN ('retracted')
                   ORDER BY updated_at DESC LIMIT 1000"""
            ).fetchall()
        scored = []
        for row in rows:
            claim_words = {m.group(0).lower() for m in _WORD.finditer(row["claim"])}
            overlap = len(words & claim_words)
            if not words or overlap:
                scored.append((overlap + float(row["confidence"]) * 0.2, row["id"]))
        scored.sort(reverse=True)
        return [self.get(belief_id) for _, belief_id in scored[:max(1, min(limit, 50))]]

    def summary_for_prompt(self, query: str, limit: int = 6) -> str:
        beliefs = self.search(query, limit)
        if not beliefs:
            return "- none retrieved"
        lines = []
        for belief in beliefs:
            supporting = sum(1 for e in belief.evidence if e["kind"] == "supports")
            contradicting = sum(1 for e in belief.evidence if e["kind"] == "contradicts")
            lines.append(
                f"- [{belief.classification}/{belief.status}] {belief.claim} "
                f"(confidence={belief.confidence:.2f}, source={belief.source or 'unknown'}, "
                f"support={supporting}, contradiction={contradicting})"
            )
        return "\n".join(lines)
