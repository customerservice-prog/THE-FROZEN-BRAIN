from __future__ import annotations

import json
from pathlib import Path

from .memory import MemoryStore


def export_memories(store: MemoryStore, path: Path) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with store.db.connect() as con, path.open("w", encoding="utf-8") as handle:
        rows = con.execute(
            "SELECT id, ts, kind, content, source, confidence, tags_json FROM memories ORDER BY id"
        ).fetchall()
        for row in rows:
            payload = {
                "format": "coldvault-memory-v1",
                "id": row["id"],
                "ts": row["ts"],
                "kind": row["kind"],
                "content": row["content"],
                "source": row["source"],
                "confidence": row["confidence"],
                "tags": json.loads(row["tags_json"]),
            }
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    store.db.add_event("memory.exported", {"path": str(path), "count": count})
    return {"path": str(path), "count": count}


def import_memories(store: MemoryStore, path: Path) -> dict:
    path = Path(path)
    imported = 0
    skipped = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("format") != "coldvault-memory-v1":
            skipped += 1
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            skipped += 1
            continue
        store.remember(
            content,
            kind=str(item.get("kind", "semantic")),
            source=str(item.get("source") or f"import:{path.name}:{line_number}"),
            confidence=float(item.get("confidence", 1.0)),
            tags=[str(x) for x in item.get("tags", [])],
        )
        imported += 1
    store.db.add_event("memory.imported", {"path": str(path), "imported": imported, "skipped": skipped})
    return {"path": str(path), "imported": imported, "skipped": skipped}
