from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def build_manifest(root: Path, output: Path | None = None) -> dict:
    root = Path(root).resolve()
    entries = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if output and path.resolve() == output.resolve():
            continue
        rel = path.relative_to(root).as_posix()
        entries.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    manifest = {"version": 1, "algorithm": "sha256", "root": root.name, "files": entries}
    if output:
        tmp = output.with_suffix(output.suffix + ".tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(output)
    return manifest


def verify_manifest(root: Path, manifest: dict) -> dict:
    root = Path(root).resolve()
    failures = []
    checked = 0
    for entry in manifest.get("files", []):
        rel = str(entry["path"])
        path = (root / rel).resolve()
        if root != path and root not in path.parents:
            failures.append({"path": rel, "error": "path escapes root"})
            continue
        if not path.is_file():
            failures.append({"path": rel, "error": "missing"})
            continue
        checked += 1
        actual = sha256_file(path)
        if actual != entry.get("sha256"):
            failures.append({"path": rel, "error": "checksum mismatch", "actual": actual, "expected": entry.get("sha256")})
    return {"ok": not failures, "checked": checked, "failures": failures}
