from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .beliefs import BeliefStore
from .config import ModelConfig, Paths, load_identity
from .continuity import ContinuityEngine
from .conversations import ConversationStore
from .db import Database
from .deliberation import DeliberationEngine
from .hardware import detect_hardware
from .knowledge import KnowledgeStore
from .memory import MemoryStore
from .model_registry import ModelRegistry
from .projects import ProjectStore
from .providers import OpenAICompatibleProvider, ProviderError
from .router import classify_request, model_hint
from .tool_protocol import ToolRegistry, permission_from_env


class ColdVault:
    def __init__(self, repo_root: Path | None = None, paths: Paths | None = None, model: ModelConfig | None = None):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.paths = (paths or Paths.from_env()).ensure()
        self.model_config = (model or ModelConfig.from_env()).validate_privacy()
        self.db = Database(self.paths.db)
        self.memory = MemoryStore(self.db)
        self.beliefs = BeliefStore(self.db)
        self.knowledge = KnowledgeStore(self.db)
        self.continuity = ContinuityEngine(self.db, self.paths.checkpoints)
        self.conversations = ConversationStore(self.db)
        self.projects = ProjectStore(self.db)
        self.identity = load_identity(self.repo_root)
        self.models = ModelRegistry(self.repo_root, self.model_config)
        self.tools = ToolRegistry(
            self.paths.workspace,
            self.memory,
            self.knowledge,
            permission=permission_from_env(),
        )

    def _provider_for_route(self, route: str) -> tuple[object, OpenAICompatibleProvider]:
        profile = self.models.select(route)
        config = profile.as_config().validate_privacy()
        return profile, OpenAICompatibleProvider(config)

    def status(self) -> dict:
        profile, provider = self._provider_for_route("general")
        return {
            "name": self.identity.get("name", "ColdVault"),
            "version": 2,
            "home": str(self.paths.home),
            "hardware": detect_hardware().as_dict(),
            "selected_profile": profile.name,
            "model": profile.model,
            "provider": provider.health(),
            "model_profiles": self.models.summary(),
            "tools": self.tools.list(),
            "database": self.db.integrity_check(),
            "cognitive_state": self.continuity.snapshot(),
        }

    def build_messages(self, user_text: str, conversation_id: str, route: str, profile_name: str) -> tuple[list[dict], list[dict]]:
        memories = self.memory.search(user_text, limit=6)
        knowledge = self.knowledge.search(user_text, limit=5)
        identity = json.dumps(self.identity, ensure_ascii=False, indent=2)
        state = json.dumps(self.continuity.snapshot(), ensure_ascii=False, indent=2)
        belief_text = self.beliefs.summary_for_prompt(user_text, limit=6)
        memory_text = "\n".join(
            f"- [{m.kind}] {m.content} (source={m.source or 'unknown'}, confidence={m.confidence:.2f})"
            for m in memories
        ) or "- none retrieved"
        knowledge_text = "\n\n".join(
            f"SOURCE: {k['source']}#{k['chunk_index']}\n{k['content']}"
            for k in knowledge
        ) or "No local knowledge passages retrieved."
        system = f"""You are the local ColdVault AI instance. You run for the user, not for a cloud service.

IDENTITY
{identity}

CURRENT COGNITIVE STATE
{state}

ROUTE
{route}: {model_hint(route)}
Selected model profile: {profile_name}

RELEVANT DURABLE MEMORY
{memory_text}

LOCAL KNOWLEDGE
{knowledge_text}

Rules:
- Treat retrieved memory as evidence with provenance, not infallible truth.
- Say when information is uncertain or unavailable.
- Never claim a tool ran unless the system actually ran it.
- Prefer local knowledge and verification when available.
- Keep durable memory distinct from temporary conversation context.
- When local knowledge materially supports an answer, identify its SOURCE label.
"""
        history = self.conversations.history(conversation_id, limit=24)
        messages = [{"role": "system", "content": system}]
        for item in history:
            if item["role"] in {"user", "assistant"}:
                messages.append({"role": item["role"], "content": item["content"]})
        return messages, knowledge

    def chat(self, user_text: str, conversation_id: str = "default") -> dict:
        text = user_text.strip()
        if not text:
            raise ValueError("message cannot be empty")
        conversation_id = self.conversations.ensure(conversation_id)
        self.conversations.append(conversation_id, "user", text)
        self.db.add_event("chat.user", {"text": text, "conversation_id": conversation_id})
        route = classify_request(text)
        profile, provider = self._provider_for_route(route)
        messages, knowledge = self.build_messages(text, conversation_id, route, profile.name)
        try:
            answer = provider.chat(messages)
            ok = True
        except ProviderError as exc:
            answer = (
                "The ColdVault continuity core is running, but the selected local model did not answer. "
                f"Profile: {profile.name}; model: {profile.model}; endpoint: {profile.base_url}. "
                f"Provider error: {exc}"
            )
            ok = False
        metadata = json.dumps({"route": route, "profile": profile.name, "provider_ok": ok}, sort_keys=True)
        self.conversations.append(conversation_id, "assistant", answer, metadata)
        self.db.add_event(
            "chat.assistant",
            {"text": answer, "provider_ok": ok, "conversation_id": conversation_id, "route": route, "profile": profile.name},
        )
        sources = [{"source": k["source"], "chunk_index": k["chunk_index"], "sha256": k["sha256"]} for k in knowledge]
        return {
            "ok": ok,
            "answer": answer,
            "route": route,
            "profile": profile.name,
            "model": profile.model,
            "conversation_id": conversation_id,
            "sources": sources,
        }

    def deep_think(self, user_text: str, conversation_id: str = "default", attempts: int = 2) -> dict:
        text = user_text.strip()
        if not text:
            raise ValueError("message cannot be empty")
        conversation_id = self.conversations.ensure(conversation_id)
        self.conversations.append(conversation_id, "user", text)
        self.db.add_event("deliberation.started", {"conversation_id": conversation_id, "attempts": attempts})
        profile = self.models.select("reasoning")
        messages, knowledge = self.build_messages(text, conversation_id, "reasoning", profile.name)
        engine = DeliberationEngine(self.models)
        try:
            result = engine.run(messages, attempts=attempts)
        except (ProviderError, RuntimeError) as exc:
            answer = f"Deep Think could not complete because the configured local reasoning models did not finish: {exc}"
            self.conversations.append(conversation_id, "assistant", answer, json.dumps({"deep_think": True, "ok": False}))
            self.db.add_event("deliberation.failed", {"conversation_id": conversation_id, "error": str(exc)})
            return {"ok": False, "answer": answer, "conversation_id": conversation_id, "attempts": [], "sources": []}
        self.conversations.append(
            conversation_id, "assistant", result.final,
            json.dumps({"deep_think": True, "attempts": len(result.attempts), "profile": result.synthesis_profile}, sort_keys=True),
        )
        self.db.add_event("deliberation.completed", {"conversation_id": conversation_id, "attempts": len(result.attempts)})
        sources = [{"source": k["source"], "chunk_index": k["chunk_index"], "sha256": k["sha256"]} for k in knowledge]
        return {
            "ok": True,
            "answer": result.final,
            "conversation_id": conversation_id,
            "attempts": result.attempts,
            "critique": result.critique,
            "synthesis_profile": result.synthesis_profile,
            "sources": sources,
        }

    def checkpoint(self, reason: str = "manual") -> dict:
        return self.continuity.checkpoint(reason)

    def set_state(self, changes: dict) -> dict:
        state = asdict(self.continuity.update(**changes))
        if state.get("active_project"):
            self.projects.upsert(state["active_project"], state)
        return state

    def run_tool(self, name: str, arguments: dict) -> dict:
        self.db.add_event("tool.requested", {"name": name, "arguments": arguments})
        try:
            result = self.tools.run(name, arguments)
        except Exception as exc:
            self.db.add_event("tool.failed", {"name": name, "error": repr(exc)})
            raise
        self.db.add_event("tool.completed", {"name": name})
        return {"ok": True, "tool": name, "result": result}
