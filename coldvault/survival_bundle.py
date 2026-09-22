from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from .db import utcnow
from .survival import select_survival_model

if TYPE_CHECKING:
    from .core import ColdVault


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _snapshot_sqlite(vault: "ColdVault", output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with vault.db.connect() as source:
        destination = sqlite3.connect(output)
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()


def _collect_open_exports(vault: "ColdVault", root: Path) -> dict:
    with vault.db.connect() as con:
        memories = [
            {
                "id": r["id"], "ts": r["ts"], "kind": r["kind"], "content": r["content"],
                "source": r["source"], "confidence": r["confidence"], "tags": json.loads(r["tags_json"]),
            }
            for r in con.execute(
                "SELECT id, ts, kind, content, source, confidence, tags_json FROM memories ORDER BY id"
            ).fetchall()
        ]
        beliefs = []
        for r in con.execute(
            "SELECT id, created_at, updated_at, claim, classification, confidence, status, source FROM beliefs ORDER BY created_at"
        ).fetchall():
            evidence = [
                dict(x)
                for x in con.execute(
                    "SELECT id, created_at, kind, content, source, confidence FROM belief_evidence WHERE belief_id=? ORDER BY id",
                    (r["id"],),
                ).fetchall()
            ]
            item = dict(r)
            item["evidence"] = evidence
            beliefs.append(item)
        reminders = [
            dict(r)
            for r in con.execute(
                "SELECT id, created_at, due_at, content, source, status, completed_at FROM prospective_actions ORDER BY due_at"
            ).fetchall()
        ]
        projects = [
            dict(r)
            for r in con.execute(
                "SELECT id, name, status, state_json, updated_at FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        ]
        tasks = [
            dict(r)
            for r in con.execute(
                """SELECT t.id, p.name AS project, t.title, t.details, t.status, t.created_at, t.updated_at
                   FROM tasks t JOIN projects p ON p.id=t.project_id ORDER BY t.created_at"""
            ).fetchall()
        ]
        conversations = [
            dict(r)
            for r in con.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        ]
        messages = [
            dict(r)
            for r in con.execute(
                "SELECT id, conversation_id, ts, role, content, metadata_json FROM messages ORDER BY id"
            ).fetchall()
        ]

    _write_json(root / "identity.json", vault.identity)
    _write_json(root / "cognitive-state.json", vault.continuity.snapshot())
    _write_jsonl(root / "memory" / "memories.jsonl", memories)
    _write_jsonl(root / "memory" / "beliefs.jsonl", beliefs)
    _write_jsonl(root / "memory" / "reminders.jsonl", reminders)
    _write_jsonl(root / "projects" / "projects.jsonl", projects)
    _write_jsonl(root / "projects" / "tasks.jsonl", tasks)
    _write_jsonl(root / "history" / "conversations.jsonl", conversations)
    _write_jsonl(root / "history" / "messages.jsonl", messages)
    return {
        "memories": len(memories), "beliefs": len(beliefs), "reminders": len(reminders),
        "projects": len(projects), "tasks": len(tasks), "conversations": len(conversations),
        "messages": len(messages),
    }


def _knowledge_queries(vault: "ColdVault", explicit: list[str] | None) -> list[str]:
    queries = [x.strip() for x in (explicit or []) if x and x.strip()]
    state = vault.continuity.snapshot()
    for key in ("active_project", "objective", "next_action"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            queries.append(value.strip())
    for item in vault.prospective.list("pending", limit=20):
        content = str(item.get("content", "")).strip()
        if content:
            queries.append(content)
    seen = set()
    result = []
    for query in queries:
        norm = query.lower()
        if norm not in seen:
            seen.add(norm)
            result.append(query)
    return result[:32]


def _export_critical_knowledge(vault: "ColdVault", root: Path, queries: list[str], limit: int) -> dict:
    selected: dict[tuple[str, int], dict] = {}
    per_query = max(2, min(12, limit))
    for query in queries:
        for item in vault.knowledge.search(query, limit=per_query):
            key = (str(item["source"]), int(item["chunk_index"]))
            current = selected.get(key)
            if current is None or float(item.get("score", 0.0)) > float(current.get("score", 0.0)):
                selected[key] = item
    ordered = sorted(
        selected.values(),
        key=lambda item: float(item.get("score", 0.0)),
        reverse=True,
    )[:max(1, min(limit, 500))]
    _write_json(root / "knowledge" / "queries.json", queries)
    _write_jsonl(root / "knowledge" / "critical-chunks.jsonl", ordered)
    return {"queries": len(queries), "chunks": len(ordered)}


def _manifest_for(root: Path, metadata: dict) -> dict:
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "MANIFEST.json"):
        rel = path.relative_to(root).as_posix()
        files.append({"path": rel, "bytes": path.stat().st_size, "sha256": _sha256_file(path)})
    return {
        "format": "coldvault-survival-bundle-v1",
        "created_at": utcnow(),
        "metadata": metadata,
        "files": files,
    }


def build_survival_bundle(
    vault: "ColdVault",
    output: Path,
    *,
    model_dir: Path | None = None,
    memory_bytes: int | None = None,
    include_model: bool = False,
    knowledge_queries: list[str] | None = None,
    knowledge_limit: int = 120,
) -> dict:
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="coldvault-survival-") as td:
        root = Path(td) / "COLDVAULT-SURVIVAL"
        root.mkdir(parents=True, exist_ok=True)

        checkpoint = vault.checkpoint("survival-bundle")
        _snapshot_sqlite(vault, root / "state" / "coldvault.sqlite3")
        counts = _collect_open_exports(vault, root)
        queries = _knowledge_queries(vault, knowledge_queries)
        knowledge = _export_critical_knowledge(vault, root, queries, knowledge_limit)

        checkpoint_path = Path(checkpoint["path"])
        if checkpoint_path.is_file():
            shutil.copy2(checkpoint_path, root / "state" / "latest-checkpoint.json")

        selection = None
        if model_dir is not None:
            selection = select_survival_model(Path(model_dir), memory_bytes=memory_bytes)
            _write_json(root / "model" / "selection.json", selection.as_dict())
            if include_model and selection.model_path:
                source = Path(selection.model_path)
                target = root / "model" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

        restore = {
            "format": "coldvault-survival-restore-v1",
            "instructions": [
                "Verify MANIFEST.json before trusting the bundle.",
                "Restore state/coldvault.sqlite3 into COLDVAULT_HOME as coldvault.sqlite3.",
                "Restore state/latest-checkpoint.json into COLDVAULT_HOME/checkpoints if present.",
                "Keep the open-format exports even when restoring the SQLite snapshot.",
                "Use model/selection.json to identify the selected emergency GGUF.",
                "Do not use a cloud endpoint as an automatic fallback.",
            ],
        }
        _write_json(root / "RESTORE.json", restore)

        metadata = {
            "checkpoint": checkpoint,
            "counts": counts,
            "knowledge": knowledge,
            "model_selection": selection.as_dict() if selection else None,
            "model_included": bool(include_model and selection and selection.model_path),
        }
        manifest = _manifest_for(root, metadata)
        _write_json(root / "MANIFEST.json", manifest)

        compression = zipfile.ZIP_DEFLATED
        with zipfile.ZipFile(output, "w", compression=compression, compresslevel=6) as archive:
            for path in sorted(p for p in root.rglob("*") if p.is_file()):
                rel = Path("COLDVAULT-SURVIVAL") / path.relative_to(root)
                if path.suffix.lower() == ".gguf":
                    info = zipfile.ZipInfo.from_file(path, rel.as_posix())
                    with path.open("rb") as handle:
                        archive.writestr(info, handle.read(), compress_type=zipfile.ZIP_STORED)
                else:
                    archive.write(path, rel.as_posix())

    return {
        "ok": True,
        "path": str(output),
        "bytes": output.stat().st_size,
        "sha256": _sha256_file(output),
        "manifest": manifest,
    }


def verify_survival_bundle(path: Path) -> dict:
    path = Path(path).expanduser().resolve()
    failures = []
    with zipfile.ZipFile(path, "r") as archive:
        manifest_name = "COLDVAULT-SURVIVAL/MANIFEST.json"
        try:
            manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        except KeyError:
            return {"ok": False, "path": str(path), "failures": [{"error": "MANIFEST.json missing"}]}
        if manifest.get("format") != "coldvault-survival-bundle-v1":
            failures.append({"error": "unsupported bundle format", "format": manifest.get("format")})
        names = set(archive.namelist())
        for entry in manifest.get("files", []):
            name = "COLDVAULT-SURVIVAL/" + str(entry["path"])
            if name not in names:
                failures.append({"path": entry["path"], "error": "missing"})
                continue
            raw = archive.read(name)
            if len(raw) != int(entry["bytes"]):
                failures.append({"path": entry["path"], "error": "size mismatch"})
                continue
            actual = _sha256_bytes(raw)
            if actual != entry["sha256"]:
                failures.append({
                    "path": entry["path"], "error": "checksum mismatch",
                    "expected": entry["sha256"], "actual": actual,
                })
    return {
        "ok": not failures,
        "path": str(path),
        "bundle_sha256": _sha256_file(path),
        "files_checked": len(manifest.get("files", [])),
        "failures": failures,
        "metadata": manifest.get("metadata", {}),
    }
