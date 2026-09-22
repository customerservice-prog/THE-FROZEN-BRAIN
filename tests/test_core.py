from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coldvault.config import ModelConfig, Paths
from coldvault.core import ColdVault
from coldvault.tools import ToolPolicy, WorkspaceTools


class ColdVaultTests(unittest.TestCase):
    def make_vault(self, root: Path) -> ColdVault:
        paths = Paths(root, root / "db.sqlite3", root / "knowledge", root / "checkpoints", root / "workspace", root / "logs").ensure()
        return ColdVault(paths=paths, model=ModelConfig(name="test", base_url="http://127.0.0.1:9/v1", timeout_seconds=1))

    def test_memory_search(self):
        with tempfile.TemporaryDirectory() as td:
            vault = self.make_vault(Path(td))
            vault.memory.remember("Generator spark was confirmed", source="test")
            found = vault.memory.search("generator spark")
            self.assertTrue(found)
            self.assertIn("spark", found[0].content.lower())

    def test_checkpoint_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            vault = self.make_vault(Path(td))
            vault.set_state({"active_project": "Alpha", "next_action": "Test"})
            vault.checkpoint("unit-test")
            restored = vault.continuity.restore_latest()
            self.assertEqual(restored.active_project, "Alpha")
            self.assertEqual(restored.next_action, "Test")

    def test_workspace_escape_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            tools = WorkspaceTools(Path(td), ToolPolicy(allow_reads=True, allow_writes=True))
            with self.assertRaises(PermissionError):
                tools.write_text("../escape.txt", "no")

    def test_knowledge_retrieval(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = self.make_vault(root)
            f = root / "guide.txt"
            f.write_text("Carburetor jet cleaning procedure and fuel flow inspection", encoding="utf-8")
            vault.knowledge.ingest_file(f, "guide.txt")
            found = vault.knowledge.search("fuel carburetor")
            self.assertTrue(found)
            self.assertEqual(found[0]["source"], "guide.txt")


if __name__ == "__main__":
    unittest.main()
