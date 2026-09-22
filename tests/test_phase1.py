from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from coldvault.archive import build_manifest, verify_manifest
from coldvault.config import ModelConfig, Paths
from coldvault.core import ColdVault
from coldvault.model_registry import ModelRegistry
from coldvault.portability import export_memories, import_memories
from coldvault.tool_protocol import Permission, ToolRegistry


class PhaseOneTests(unittest.TestCase):
    def make_vault(self, root: Path) -> ColdVault:
        paths = Paths(
            home=root,
            db=root / "db.sqlite3",
            knowledge=root / "knowledge",
            checkpoints=root / "checkpoints",
            workspace=root / "workspace",
            logs=root / "logs",
        ).ensure()
        return ColdVault(
            repo_root=root,
            paths=paths,
            model=ModelConfig(name="test-local", base_url="http://127.0.0.1:9/v1", timeout_seconds=1),
        )

    def test_conversations_persist_messages(self):
        with tempfile.TemporaryDirectory() as td:
            vault = self.make_vault(Path(td))
            cid = vault.conversations.create("Test thread")
            vault.conversations.append(cid, "user", "hello")
            vault.conversations.append(cid, "assistant", "world")
            history = vault.conversations.history(cid)
            self.assertEqual([x["role"] for x in history], ["user", "assistant"])
            self.assertEqual(history[-1]["content"], "world")

    def test_projects_and_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            vault = self.make_vault(Path(td))
            task = vault.projects.add_task("Bunker", "Verify archive", "Run checksums")
            self.assertEqual(task["status"], "todo")
            vault.projects.set_task_status(task["id"], "done")
            tasks = vault.projects.tasks("Bunker")
            self.assertEqual(tasks[0]["status"], "done")

    def test_tool_permission_gate(self):
        with tempfile.TemporaryDirectory() as td:
            vault = self.make_vault(Path(td))
            tools = ToolRegistry(Path(td) / "workspace2", vault.memory, vault.knowledge, Permission.READ)
            with self.assertRaises(PermissionError):
                tools.run("workspace.write", {"path": "x.txt", "content": "blocked"})
            self.assertIsInstance(tools.run("workspace.list", {"path": "."}), list)

    def test_archive_manifest_detects_change(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.txt").write_text("alpha", encoding="utf-8")
            manifest = build_manifest(root)
            self.assertTrue(verify_manifest(root, manifest)["ok"])
            (root / "a.txt").write_text("changed", encoding="utf-8")
            result = verify_manifest(root, manifest)
            self.assertFalse(result["ok"])
            self.assertEqual(result["failures"][0]["error"], "checksum mismatch")

    def test_remote_provider_is_rejected_by_default(self):
        old = os.environ.pop("COLDVAULT_ALLOW_REMOTE_PROVIDER", None)
        try:
            with self.assertRaises(ValueError):
                ModelConfig(base_url="https://example.com/v1").validate_privacy()
            ModelConfig(base_url="http://192.168.1.10:11434/v1").validate_privacy()
        finally:
            if old is not None:
                os.environ["COLDVAULT_ALLOW_REMOTE_PROVIDER"] = old

    def test_registry_falls_back_to_explicit_model(self):
        with tempfile.TemporaryDirectory() as td:
            fallback = ModelConfig(name="my-model", base_url="http://127.0.0.1:11434/v1")
            registry = ModelRegistry(Path(td), fallback)
            self.assertEqual(registry.select("coding").model, "my-model")

    def test_memory_export_import(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = self.make_vault(root / "a")
            vault.memory.remember("Preserve this fact", kind="semantic", source="unit")
            target = root / "memories.jsonl"
            exported = export_memories(vault.memory, target)
            self.assertEqual(exported["count"], 1)

            restored = self.make_vault(root / "b")
            imported = import_memories(restored.memory, target)
            self.assertEqual(imported["imported"], 1)
            self.assertEqual(restored.memory.search("preserve fact")[0].source, "unit")


if __name__ == "__main__":
    unittest.main()
