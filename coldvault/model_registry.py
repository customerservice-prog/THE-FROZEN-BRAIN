from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .config import ModelConfig


@dataclass(frozen=True)
class ModelProfile:
    name: str
    purpose: str
    model: str
    base_url: str
    capabilities: frozenset[str]
    priority: int = 50
    enabled: bool = True

    def as_config(self) -> ModelConfig:
        return ModelConfig(
            name=self.model,
            base_url=self.base_url,
            api_key=os.environ.get("COLDVAULT_API_KEY", "coldvault-local"),
            timeout_seconds=int(os.environ.get("COLDVAULT_TIMEOUT", "120")),
        )


class ModelRegistry:
    ROUTE_CAPABILITY = {
        "general": "general",
        "reasoning": "reasoning",
        "coding": "coding",
        "vision": "vision",
    }

    def __init__(self, repo_root: Path, fallback: ModelConfig):
        self.repo_root = repo_root
        self.fallback = fallback
        self.profiles = self._load()

    def _load(self) -> list[ModelProfile]:
        override = os.environ.get("COLDVAULT_MODELS")
        candidates = []
        if override:
            candidates.append(Path(override))
        candidates.append(self.repo_root / "config" / "models.json")
        data = None
        for path in candidates:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                break
        profiles: list[ModelProfile] = []
        if data:
            for name, raw in data.get("profiles", {}).items():
                capabilities = raw.get("capabilities") or [raw.get("purpose", "general")]
                model = raw.get("model") or os.environ.get(f"COLDVAULT_MODEL_{name.upper()}") or self.fallback.name
                base_url = raw.get("base_url") or os.environ.get(f"COLDVAULT_URL_{name.upper()}") or self.fallback.base_url
                profiles.append(ModelProfile(
                    name=name,
                    purpose=str(raw.get("purpose", name)),
                    model=str(model),
                    base_url=str(base_url).rstrip("/"),
                    capabilities=frozenset(str(x) for x in capabilities),
                    priority=int(raw.get("priority", 50)),
                    enabled=bool(raw.get("enabled", True)),
                ))
        if not profiles:
            profiles.append(ModelProfile(
                name="default", purpose="general", model=self.fallback.name, base_url=self.fallback.base_url,
                capabilities=frozenset({"general", "reasoning", "coding"}), priority=50,
            ))
        return profiles

    def candidates(self, route: str) -> list[ModelProfile]:
        capability = self.ROUTE_CAPABILITY.get(route, "general")
        eligible = [p for p in self.profiles if p.enabled and capability in p.capabilities]
        if not eligible and capability != "general":
            eligible = [p for p in self.profiles if p.enabled and "general" in p.capabilities]
        if not eligible:
            eligible = [p for p in self.profiles if p.enabled]
        return sorted(eligible, key=lambda p: p.priority, reverse=True)

    def select(self, route: str) -> ModelProfile:
        eligible = self.candidates(route)
        if not eligible:
            raise RuntimeError("no enabled local model profiles")
        return eligible[0]

    def summary(self) -> list[dict]:
        return [
            {"name": p.name, "purpose": p.purpose, "model": p.model, "base_url": p.base_url,
             "capabilities": sorted(p.capabilities), "priority": p.priority, "enabled": p.enabled}
            for p in self.profiles
        ]
