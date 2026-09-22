from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .config import ModelConfig, Paths, load_identity
from .continuity import ContinuityEngine
from .db import Database
from .knowledge import KnowledgeStore
from .memory import MemoryStore
from .providers import OpenAICompatibleProvider, ProviderError
from .router import classify_request, model_hint


class ColdVault:
    def __init__(self, repo_root: Path | None = None, paths: Paths | None = None, model: ModelConfig | None = None):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.paths = (paths or Paths.from_env()).ensure()
        self.model_config = model or ModelConfig.from_env()
        self.db = Database(self.paths.db)
        self.memory = MemoryStore(self.db)
        self.knowledge = KnowledgeStore(self.db)
        self.continuity = ContinuityEngine(self.db, self.paths.checkpoints)
        self.identity = load_identity(self.repo_root)
        self.provider = OpenAICompatibleProvider(self.model_config)

    def status(self) -> dict:
        return {
            "name": self.identity.get("name", "ColdVault"),
            "version": 1,
            "home": str(self.paths.home),
            "model": self.model_config.name,
            "provider": self.provider.health(),
            "cognitive_state": self.continuity.snapshot(),
        }

    def build_messages(self, user_text: str) -> list[dict]:
        route = classify_request(user_text)
        memories = self.memory.search(user_text, limit=6)
        knowledge = self.knowledge.search(user_text, limit=5)
        identity = json.dumps(self.identity, ensure_ascii=False, indent=2)
        state = json.dumps(self.continuity.snapshot(), ensure_ascii=False, indent=2)
        memory_text = "\n".join(f"- [{m.kind}] {m.content} (source={m.source or 'unknown'}, confidence={m.confidence:.2f})" for m in memories) or "- none retrieved"
        knowledge_text = "\n\n".join(f"SOURCE: {k['source']}#{k['chunk_index']}\n{k['content']}" for k in knowledge) or "No local knowledge passages retrieved."
        system = f"""You are the local ColdVault AI instance. You run for the user, not for a cloud service.

IDENTITY\n{identity}

CURRENT COGNITIVE STATE\n{state}

ROUTE\n{route}: {model_hint(route)}

RELEVANT DURABLE MEMORY\n{memory_text}

LOCAL KNOWLEDGE\n{knowledge_text}

Rules:
- Treat retrieved memory as evidence with provenance, not infallible truth.
- Say when information is uncertain or unavailable.
- Never claim a tool ran unless the system actually ran it.
- Prefer local knowledge and verification when available.
- Keep the user's durable state distinct from temporary conversation context.
"""
        return [{"role": "system", "content": system}, {"role": "user", "content": user_text}]

    def chat(self, user_text: str) -> dict:
        text = user_text.strip()
        if not text:
            raise ValueError("message cannot be empty")
        self.db.add_event("chat.user", {"text": text})
        try:
            answer = self.provider.chat(self.build_messages(text))
            ok = True
        except ProviderError as exc:
            answer = (
                "The ColdVault core is running, but no compatible local model answered. "
                f"Configured endpoint: {self.model_config.base_url}, model: {self.model_config.name}. "
                f"Provider error: {exc}"
            )
            ok = False
        self.db.add_event("chat.assistant", {"text": answer, "provider_ok": ok})
        return {"ok": ok, "answer": answer, "route": classify_request(text)}

    def checkpoint(self, reason: str = "manual") -> dict:
        return self.continuity.checkpoint(reason)

    def set_state(self, changes: dict) -> dict:
        return asdict(self.continuity.update(**changes))
