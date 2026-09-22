from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coldvault.ark import verify_ark
from coldvault.config import ModelConfig, Paths
from coldvault.core import ColdVault


def make_paths(root: Path) -> Paths:
    return Paths(
        root,
        root / "coldvault.sqlite3",
        root / "knowledge",
        root / "checkpoints",
        root / "workspace",
        root / "logs",
    ).ensure()


def software_resurrection_test() -> dict:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        paths = make_paths(root)
        model = ModelConfig(
            name="resurrection-no-model",
            base_url="http://127.0.0.1:9/v1",
            timeout_seconds=1,
        )

        first = ColdVault(paths=paths, model=model)
        first.memory.remember(
            "Resurrection marker: generator spark was confirmed.",
            kind="episodic",
            source="resurrection-test",
        )
        first.set_state({
            "active_project": "ColdVault resurrection test",
            "objective": "Prove durable cognition survives restart",
        })
        first.checkpoint("resurrection-midpoint")
        first.set_state({
            "next_action": "Verify post-checkpoint journal replay",
            "uncertainties": ["No live model is required for this test"],
        })
        due_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        reminder_id = first.prospective.create(
            "Verify due prospective memory after restart",
            due_at,
            source="resurrection-test",
        )
        source = root / "survival-manual.txt"
        source.write_text(
            "Emergency recovery procedure: restore state, verify checksums, then start local inference.",
            encoding="utf-8",
        )
        first.knowledge.ingest_file(source, "knowledge/survival-manual.txt")

        second = ColdVault(paths=paths, model=model)
        state = second.continuity.snapshot()
        memory_ok = bool(second.memory.search("generator spark"))
        knowledge_ok = bool(second.knowledge.search("recovery checksums"))
        due_ids = {item["id"] for item in second.prospective.due()}
        db = second.db.integrity_check()

        checks = {
            "database_integrity": bool(db["ok"]),
            "memory_restored": memory_ok,
            "knowledge_restored": knowledge_ok,
            "checkpoint_state_restored": state.get("active_project") == "ColdVault resurrection test",
            "journal_replay_restored": state.get("next_action") == "Verify post-checkpoint journal replay",
            "prospective_memory_restored": reminder_id in due_ids,
        }
        return {
            "ok": all(checks.values()),
            "checks": checks,
            "state": state,
        }


def ark_test(root: Path, strict: bool) -> dict:
    manifest_path = root / "COLDVAULT-ARK.json"
    if not manifest_path.is_file():
        return {
            "ok": False,
            "error": f"Ark manifest not found: {manifest_path}",
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return verify_ark(root, manifest, strict=strict)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ColdVault offline resurrection test. No model or WAN connection is required."
    )
    parser.add_argument("--ark", help="Optional ColdVault Ark directory to verify")
    parser.add_argument("--strict", action="store_true", help="Fail Ark verification on unlisted files")
    args = parser.parse_args()

    software = software_resurrection_test()
    result = {"software_resurrection": software}
    ok = software["ok"]

    if args.ark:
        ark = ark_test(Path(args.ark).resolve(), args.strict)
        result["ark"] = ark
        ok = ok and bool(ark.get("ok"))

    result["ok"] = ok
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
