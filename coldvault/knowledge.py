from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from .db import Database, utcnow
from .documents import extract_document
from .embeddings import EmbeddingError, LocalEmbeddingProvider, cosine_similarity

_WORD = re.compile(r"[A-Za-z0-9_'-]+")


def _token_list(text: str) -> list[str]:
    return [x.group(0).lower() for x in _WORD.finditer(text) if len(x.group(0)) > 1]


def _chunks(text: str, size: int = 2200, overlap: int = 250):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = max(
                text.rfind("\n\n", start + size // 2, end),
                text.rfind("\n", start + size // 2, end),
                text.rfind(" ", start + size // 2, end),
            )
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            yield chunk
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)


class KnowledgeStore:
    def __init__(self, db: Database, embedder: LocalEmbeddingProvider | None = None):
        self.db = db
        self.embedder = embedder

    @property
    def embedding_model(self) -> str | None:
        return self.embedder.config.name if self.embedder else None

    def _store_embeddings(self, pairs: list[tuple[int, str]]) -> dict:
        if not self.embedder or not pairs:
            return {"enabled": False, "model": None, "embedded": 0}
        embedded = 0
        try:
            for start in range(0, len(pairs), 24):
                batch = pairs[start:start + 24]
                vectors = self.embedder.embed([text for _, text in batch])
                with self.db.connect() as con:
                    for (chunk_id, _), vector in zip(batch, vectors):
                        con.execute(
                            """INSERT OR REPLACE INTO knowledge_embeddings
                               (chunk_id, model, dimensions, vector_json, created_at)
                               VALUES (?, ?, ?, ?, ?)""",
                            (
                                chunk_id,
                                self.embedder.config.name,
                                len(vector),
                                json.dumps(vector, separators=(",", ":")),
                                utcnow(),
                            ),
                        )
                        embedded += 1
            return {"enabled": True, "model": self.embedder.config.name, "embedded": embedded}
        except EmbeddingError as exc:
            self.db.add_event(
                "knowledge.embedding_failed",
                {"model": self.embedder.config.name, "error": str(exc), "attempted": len(pairs)},
            )
            return {
                "enabled": True,
                "model": self.embedder.config.name,
                "embedded": embedded,
                "error": str(exc),
            }

    def ingest_file(self, path: Path, logical_path: str | None = None) -> dict:
        path = Path(path)
        raw = path.read_bytes()
        import hashlib
        sha = hashlib.sha256(raw).hexdigest()
        extracted = extract_document(path)
        source = logical_path or str(path)
        if not extracted.text.strip():
            raise ValueError(f"no extractable text found in {path.name}")

        chunk_pairs: list[tuple[int, str]] = []
        with self.db.connect() as con:
            con.execute("DELETE FROM knowledge_chunks WHERE source_path = ?", (source,))
            for i, chunk in enumerate(_chunks(extracted.text)):
                cur = con.execute(
                    "INSERT INTO knowledge_chunks(source_path, chunk_index, content, source_sha256) VALUES (?, ?, ?, ?)",
                    (source, i, chunk, sha),
                )
                chunk_pairs.append((int(cur.lastrowid), chunk))

        embedding = self._store_embeddings(chunk_pairs)
        self.db.add_event(
            "knowledge.ingested",
            {
                "source": source,
                "sha256": sha,
                "chunks": len(chunk_pairs),
                "media_type": extracted.media_type,
                "extractor": extracted.extractor,
                "embedding": embedding,
            },
        )
        return {
            "source": source,
            "sha256": sha,
            "chunks": len(chunk_pairs),
            "media_type": extracted.media_type,
            "extractor": extracted.extractor,
            "embedding": embedding,
        }

    def reindex_embeddings(self) -> dict:
        if not self.embedder:
            return {"enabled": False, "model": None, "embedded": 0}
        with self.db.connect() as con:
            con.execute(
                "DELETE FROM knowledge_embeddings WHERE model = ?",
                (self.embedder.config.name,),
            )
            rows = con.execute(
                "SELECT id, content FROM knowledge_chunks ORDER BY id"
            ).fetchall()
        result = self._store_embeddings([(int(r["id"]), r["content"]) for r in rows])
        self.db.add_event("knowledge.embeddings_reindexed", result)
        return result

    def _lexical_scores(self, rows, query: str) -> dict[int, float]:
        query_terms = _token_list(query)
        if not query_terms or not rows:
            return {}
        docs = {int(row["id"]): _token_list(row["content"]) for row in rows}
        n_docs = len(docs)
        avg_len = sum(len(tokens) for tokens in docs.values()) / max(1, n_docs)
        df = Counter()
        for tokens in docs.values():
            for term in set(tokens):
                df[term] += 1
        q_counts = Counter(query_terms)
        scores: dict[int, float] = {}
        k1 = 1.35
        b = 0.72
        for chunk_id, tokens in docs.items():
            tf = Counter(tokens)
            dl = max(1, len(tokens))
            score = 0.0
            for term, qtf in q_counts.items():
                if tf[term] == 0:
                    continue
                idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
                denom = tf[term] + k1 * (1.0 - b + b * dl / max(1.0, avg_len))
                score += idf * ((tf[term] * (k1 + 1.0)) / denom) * (1.0 + math.log(qtf))
            if query.strip().lower() in rows_by_id(rows, chunk_id)["content"].lower():
                score += 1.5
            if score > 0:
                scores[chunk_id] = score
        return scores

    def _semantic_scores(self, rows, query: str) -> dict[int, float]:
        if not self.embedder or not query.strip():
            return {}
        try:
            query_vector = self.embedder.embed([query])[0]
        except EmbeddingError as exc:
            self.db.add_event(
                "knowledge.embedding_query_failed",
                {"model": self.embedder.config.name, "error": str(exc)},
            )
            return {}
        with self.db.connect() as con:
            vector_rows = con.execute(
                """SELECT chunk_id, vector_json FROM knowledge_embeddings
                   WHERE model = ?""",
                (self.embedder.config.name,),
            ).fetchall()
        allowed = {int(row["id"]) for row in rows}
        scores: dict[int, float] = {}
        for row in vector_rows:
            chunk_id = int(row["chunk_id"])
            if chunk_id not in allowed:
                continue
            try:
                vector = [float(x) for x in json.loads(row["vector_json"])]
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            similarity = cosine_similarity(query_vector, vector)
            scores[chunk_id] = max(0.0, (similarity + 1.0) / 2.0)
        return scores

    def search(self, query: str, limit: int = 6) -> list[dict]:
        if not query.strip():
            return []
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT id, source_path, chunk_index, content, source_sha256 FROM knowledge_chunks"
            ).fetchall()
        if not rows:
            return []

        lexical = self._lexical_scores(rows, query)
        semantic = self._semantic_scores(rows, query)
        max_lex = max(lexical.values(), default=0.0)
        scored = []
        for row in rows:
            chunk_id = int(row["id"])
            lex_norm = lexical.get(chunk_id, 0.0) / max_lex if max_lex else 0.0
            sem = semantic.get(chunk_id, 0.0)
            if semantic:
                score = lex_norm * 0.58 + sem * 0.42
                mode = "hybrid"
            else:
                score = lex_norm
                mode = "lexical"
            if score > 0:
                scored.append((score, row, lex_norm, sem, mode))

        scored.sort(key=lambda item: (item[0], item[2], -int(item[1]["id"])), reverse=True)
        return [
            {
                "source": row["source_path"],
                "chunk_index": row["chunk_index"],
                "content": row["content"],
                "sha256": row["source_sha256"],
                "score": round(score, 6),
                "lexical_score": round(lex_score, 6),
                "semantic_score": round(sem_score, 6),
                "retrieval": mode,
            }
            for score, row, lex_score, sem_score, mode in scored[: max(1, min(limit, 30))]
        ]


def rows_by_id(rows, chunk_id: int):
    for row in rows:
        if int(row["id"]) == chunk_id:
            return row
    raise KeyError(chunk_id)
