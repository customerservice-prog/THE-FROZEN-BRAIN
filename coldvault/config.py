from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    home: Path
    db: Path
    knowledge: Path
    checkpoints: Path
    workspace: Path
    logs: Path

    @classmethod
    def from_env(cls) -> "Paths":
        home = Path(os.environ.get("COLDVAULT_HOME", Path.home() / ".coldvault")).expanduser().resolve()
        return cls(
            home=home,
            db=home / "coldvault.sqlite3",
            knowledge=home / "knowledge",
            checkpoints=home / "checkpoints",
            workspace=home / "workspace",
            logs=home / "logs",
        )

    def ensure(self) -> "Paths":
        self.home.mkdir(parents=True, exist_ok=True)
        self.knowledge.mkdir(parents=True, exist_ok=True)
        self.checkpoints.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        return self


@dataclass
class ModelConfig:
    name: str = "local-model"
    base_url: str = "http://127.0.0.1:11434/v1"
    api_key: str = "coldvault-local"
    timeout_seconds: int = 120

    @classmethod
    def from_env(cls) -> "ModelConfig":
        return cls(
            name=os.environ.get("COLDVAULT_MODEL", "local-model"),
            base_url=os.environ.get("COLDVAULT_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/"),
            api_key=os.environ.get("COLDVAULT_API_KEY", "coldvault-local"),
            timeout_seconds=int(os.environ.get("COLDVAULT_TIMEOUT", "120")),
        )


def load_identity(repo_root: Path | None = None) -> dict:
    override = os.environ.get("COLDVAULT_IDENTITY")
    candidates = []
    if override:
        candidates.append(Path(override))
    if repo_root:
        candidates.append(repo_root / "config" / "identity.json")
        candidates.append(repo_root / "config" / "identity.example.json")
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {
        "name": "ColdVault",
        "purpose": "A private, local-first artificial intelligence continuity system.",
        "principles": [
            "Prefer verified information over confident guessing.",
            "Preserve user control and privacy.",
            "Treat durable memory as explicit state, not hidden model state.",
        ],
    }
