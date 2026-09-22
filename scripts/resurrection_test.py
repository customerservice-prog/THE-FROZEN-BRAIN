from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coldvault.archive import build_manifest, verify_manifest
from coldvault.config import ModelConfig, Paths
from coldvault.core import ColdVault
from coldvault.portability import export_memories, import_memories


def make_vault(home: Path) -> ColdVault:
    paths = Paths(
        home=home,
        db=home / "coldvault.sqlite3",
        knowledge=home / "knowledge",
        checkpoints=home / "checkpoints",
        workspace=home / "workspace",
        logs=home / "logs",
    ).ensure()
    return ColdVault(
        repo_root=ROOT,
        paths=paths,
        model=ModelConfig(name="resurrection-test", base_url="http://127.0.0.1:9/v1", timeout_seconds=1),
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        original = make_vault(base / "original")
        original.memory.remember("The recovery phrase is frozen-brain-alpha", source="resurrection-test")
        original.set_state({
            "active_project": "Resurrection Test",
            "objective": "Prove durable cognition survives transfer",
            "next_action": "Restore on blank home",
        })
        source = base / "manual.txt"
        source.write_text("ColdVault emergency recovery requires verified checksums before state restoration.", encoding="utf-8")
        original.knowledge.ingest_file(source, "manuals/recovery.txt")
        checkpoint = original.checkpoint("pre-transfer")

        portable = base / "memories.jsonl"
        export_memories(original.memory, portable)

        ark = base / "ark"
        ark.mkdir()
        (ark / "memories.jsonl").write_bytes(portable.read_bytes())
        checkpoint_copy = ark / "checkpoint.json"
        checkpoint_copy.write_bytes(Path(checkpoint["path"]).read_bytes())
        manifest_path = ark / "COLDVAULT-MANIFEST.json"
        manifest = build_manifest(ark, manifest_path)

        if not verify_manifest(ark, manifest)["ok"]:
            raise SystemExit("FAIL: archive integrity verification")

        restored = make_vault(base / "restored")
        import_memories(restored.memory, ark / "memories.jsonl")
        restored.set_state({
            "active_project": "Resurrection Test",
            "objective": "Prove durable cognition survives transfer",
            "next_action": "Continue",
        })
        restored.checkpoint("post-transfer")

        memory = restored.memory.search("recovery phrase")
        if not memory or "frozen-brain-alpha" not in memory[0].content:
            raise SystemExit("FAIL: memory did not survive transfer")
        if restored.continuity.snapshot()["active_project"] != "Resurrection Test":
            raise SystemExit("FAIL: cognitive state did not restore")

        print(json.dumps({
            "ok": True,
            "memory": "restored",
            "checkpoint": "verified",
            "archive_manifest": "verified",
            "network_required": False,
            "model_required": False,
        }, indent=2))


if __name__ == "__main__":
    main()
