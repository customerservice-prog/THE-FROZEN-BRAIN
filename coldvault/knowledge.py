from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .db import Database

_WORD = re.compile(r"[A-Za-z0-9_'-]+")


def _tokens(text: str) -> set[str]:
    return {x.group(0).lower() for x in _WORD.finditer(text) if len(x.group(0)) > 1}


def _chunks(text: str, size: int = 2200, overlap: int = 250):
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        yield text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


class KnowledgeStore:
    TEXT_EXTENSIONS = {".txt", ".md", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".csv", ".yaml", ".yml", ".toml", ".ini", ".log"}

    def __init__(self, db: Database):
        self.db = db

    def ingest_file(self, path: Path, logical_path: str | None = None) -> dict:
        path = Path(path)
        if path.suffix.lower() not in self.TEXT_EXTENSIONS:
            raise ValueError(f"v0.1 only ingests text-like files; unsupported extension: {path.suffix}")
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8", errors="replace")
        source = logical_path or str(path)
        with self.db.connect() as con:
            con.execute("DELETE FROM knowledge_chunks WHERE source_path = ?", (source,))
            count = 0
            for i, chunk in enumerate(_chunks(text)):
                if not chunk.strip():
                    continue
                con.execute(
                    "INSERT INTO knowledge_chunks(source_path, chunk_index, content, source_sha256) VALUES (?, ?, ?, ?)",
                    (source, i, chunk, sha),
                )
                count += 1
        self.db.add_event("knowledge.ingested", {"source": source, "sha256": sha, "chunks": count})
        return {"source": source, "sha256": sha, "chunks": count}

    def search(self, query: str, limit: int = 6) -> list[dict]:
        q = _tokens(query)
        if not q:
            return []
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT source_path, chunk_index, content, source_sha256 FROM knowledge_chunks"
            ).fetchall()
        scored = []
        for row in rows:
            tokens = _tokens(row["content"])
            score = len(tokens & q)
            if score:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "source": r["source_path"], "chunk_index": r["chunk_index"], "content": r["content"],
                "sha256": r["source_sha256"], "score": score,
            }
            for score, r in scored[: max(1, min(limit, 30))]
        ]
