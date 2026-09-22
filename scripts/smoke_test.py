from __future__ import annotations

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coldvault.config import ModelConfig, Paths
from coldvault.core import ColdVault


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        paths = Paths(home, home / "db.sqlite3", home / "knowledge", home / "checkpoints", home / "workspace", home / "logs").ensure()
        vault = ColdVault(paths=paths, model=ModelConfig(name="none", base_url="http://127.0.0.1:9/v1", timeout_seconds=1))
        vault.memory.remember("ColdVault smoke test memory", source="smoke-test")
        assert vault.memory.search("smoke test")
        vault.set_state({"active_project": "self-test", "objective": "verify continuity", "next_action": "checkpoint"})
        cp = vault.checkpoint("smoke-test")
        assert Path(cp["path"]).exists()
        assert vault.continuity.restore_latest().active_project == "self-test"
        source = home / "manual.txt"
        source.write_text("Emergency inverter reset procedure: isolate load, inspect DC input, then restart.", encoding="utf-8")
        vault.knowledge.ingest_file(source, "manuals/inverter.txt")
        assert vault.knowledge.search("inverter restart")
        print("PASS: ColdVault memory, continuity, checkpoint integrity, and local knowledge retrieval")


if __name__ == "__main__":
    main()
