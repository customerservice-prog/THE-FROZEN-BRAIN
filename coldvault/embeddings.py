from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import EmbeddingConfig


class EmbeddingError(RuntimeError):
    pass


class LocalEmbeddingProvider:
    """OpenAI-compatible embeddings client restricted by EmbeddingConfig privacy rules."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config.validate_privacy()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.config.base_url}/embeddings"
        payload = json.dumps({
            "model": self.config.name,
            "input": texts,
        }).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EmbeddingError(f"local embedding endpoint unavailable or invalid: {exc}") from exc
        try:
            rows = sorted(body["data"], key=lambda row: int(row.get("index", 0)))
            vectors = [[float(value) for value in row["embedding"]] for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError(f"unexpected embedding response shape: {body!r}") from exc
        if len(vectors) != len(texts):
            raise EmbeddingError(f"embedding endpoint returned {len(vectors)} vectors for {len(texts)} inputs")
        if any(not vector for vector in vectors):
            raise EmbeddingError("embedding endpoint returned an empty vector")
        return vectors

    def health(self) -> dict:
        try:
            vector = self.embed(["coldvault health probe"])[0]
            return {
                "ok": True,
                "endpoint": self.config.base_url,
                "model": self.config.name,
                "dimensions": len(vector),
            }
        except EmbeddingError as exc:
            return {
                "ok": False,
                "endpoint": self.config.base_url,
                "model": self.config.name,
                "error": str(exc),
            }


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
