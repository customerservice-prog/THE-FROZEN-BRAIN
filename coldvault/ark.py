from __future__ import annotations

import json
import platform
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .archive import sha256_file


CRITICAL_CATEGORIES = (
    "source",
    "models",
    "runtimes",
    "packages",
    "state",
    "knowledge",
    "recovery_docs",
)

RECOMMENDED_CATEGORIES = (
    "os_media",
    "drivers",
    "firmware",
    "hardware_docs",
)


def _category(path: Path) -> str:
    parts = [part.lower() for part in path.parts]
    suffix = path.suffix.lower()
    name = path.name.lower()

    # Explicit archive directories outrank generic file extensions. A firmware
    # blob named update.bin must never be mislabeled as a model weight.
    if any(part in {"runtimes", "runtime", "engines", "inference"} for part in parts):
        return "runtimes"
    if any(part in {"packages", "wheels", "package-cache"} for part in parts):
        return "packages"
    if any(part in {"os", "os-media", "installers"} for part in parts):
        return "os_media"
    if "drivers" in parts:
        return "drivers"
    if "firmware" in parts:
        return "firmware"
    if "models" in parts:
        return "models"
    if suffix in {".gguf", ".safetensors", ".onnx", ".pt", ".pth"}:
        return "models"
    if suffix in {".whl", ".deb", ".rpm", ".apk", ".msi", ".pkg"}:
        return "packages"
    if suffix in {".iso", ".img"}:
        return "os_media"
    if suffix in {".rom", ".fw"}:
        return "firmware"
    if any(part in {"hardware-docs", "hardware_docs"} for part in parts):
        return "hardware_docs"
    if suffix in {".sqlite3", ".sqlite", ".db"} or any(
        part in {"state", "checkpoints", "coldvault-data", "memory"} for part in parts
    ):
        return "state"
    if "knowledge" in parts:
        return "knowledge"
    if "recovery" in name or any(part in {"recovery", "runbooks"} for part in parts):
        return "recovery_docs"
    if "docs" in parts and any(word in name for word in ("recover", "restore", "resurrect", "offline")):
        return "recovery_docs"
    if any(part in {"coldvault", "src", "source", "tests", "scripts", ".github"} for part in parts):
        return "source"
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".c", ".cc", ".cpp", ".h", ".java", ".kt"}:
        return "source"
    if suffix in {".md", ".txt", ".pdf", ".docx", ".html", ".htm"}:
        return "documentation"
    return "other"


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{value} B"


def build_ark_catalog(
    root: Path,
    manifest_path: Path | None = None,
    index_path: Path | None = None,
) -> dict:
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Ark root is not a directory: {root}")

    manifest_path = (manifest_path or (root / "COLDVAULT-ARK.json")).resolve()
    index_path = (index_path or (root / "COLDVAULT-INDEX.md")).resolve()
    excluded = {manifest_path, index_path}

    files = []
    counts = Counter()
    bytes_by_category: dict[str, int] = defaultdict(int)
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        resolved = path.resolve()
        if resolved in excluded:
            continue
        rel = path.relative_to(root)
        category = _category(rel)
        size = path.stat().st_size
        entry = {
            "path": rel.as_posix(),
            "category": category,
            "bytes": size,
            "sha256": sha256_file(path),
        }
        files.append(entry)
        counts[category] += 1
        bytes_by_category[category] += size

    present = {entry["category"] for entry in files}
    missing_critical = [name for name in CRITICAL_CATEGORIES if name not in present]
    missing_recommended = [name for name in RECOMMENDED_CATEGORIES if name not in present]
    total_bytes = sum(entry["bytes"] for entry in files)

    manifest = {
        "format": "coldvault-ark-v1",
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root": root.name,
        "algorithm": "sha256",
        "host_record": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "summary": {
            "files": len(files),
            "bytes": total_bytes,
            "categories": dict(sorted(counts.items())),
            "category_bytes": dict(sorted(bytes_by_category.items())),
            "missing_critical": missing_critical,
            "missing_recommended": missing_recommended,
            "complete": not missing_critical,
        },
        "files": files,
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(manifest_path)

    lines = [
        "# ColdVault Ark Index",
        "",
        f"Generated: {manifest['created_at']}",
        f"Files: {len(files)}",
        f"Total size: {_format_bytes(total_bytes)}",
        f"Manifest: `{manifest_path.name}`",
        "",
        "## Completeness",
        "",
    ]
    if missing_critical:
        lines += [
            "**NOT resurrection-complete.** Critical categories are missing:",
            "",
            *[f"- {name}" for name in missing_critical],
        ]
    else:
        lines.append("All critical artifact categories are represented. This does not replace a real resurrection test.")
    if missing_recommended:
        lines += ["", "Recommended categories not present:", "", *[f"- {name}" for name in missing_recommended]]

    lines += ["", "## Category inventory", "", "| Category | Files | Size |", "|---|---:|---:|"]
    for category in sorted(counts):
        lines.append(f"| {category} | {counts[category]} | {_format_bytes(bytes_by_category[category])} |")

    lines += [
        "",
        "## Recovery order",
        "",
        "1. Verify `COLDVAULT-ARK.json` against every listed SHA-256.",
        "2. Restore operating-system media, drivers, firmware, and runtime dependencies.",
        "3. Restore ColdVault source and its package archive.",
        "4. Restore model weights and inference runtimes.",
        "5. Restore durable state, checkpoints, and knowledge sources.",
        "6. Start ColdVault without WAN access and run the resurrection test.",
        "7. Only after the offline test passes should optional network access be considered.",
        "",
        "## Files",
        "",
        "| Category | Path | Size | SHA-256 |",
        "|---|---|---:|---|",
    ]
    for entry in files:
        lines.append(
            f"| {entry['category']} | `{entry['path']}` | {_format_bytes(entry['bytes'])} | `{entry['sha256']}` |"
        )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_index = index_path.with_suffix(index_path.suffix + ".tmp")
    tmp_index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp_index.replace(index_path)
    return manifest


def verify_ark(root: Path, manifest: dict, *, strict: bool = False) -> dict:
    root = Path(root).resolve()
    failures = []
    checked = 0
    listed: set[str] = set()
    for entry in manifest.get("files", []):
        rel = str(entry.get("path", ""))
        listed.add(rel)
        path = (root / rel).resolve()
        if root != path and root not in path.parents:
            failures.append({"path": rel, "error": "path escapes root"})
            continue
        if not path.is_file():
            failures.append({"path": rel, "error": "missing"})
            continue
        checked += 1
        size = path.stat().st_size
        if size != int(entry.get("bytes", -1)):
            failures.append(
                {"path": rel, "error": "size mismatch", "expected": entry.get("bytes"), "actual": size}
            )
            continue
        actual = sha256_file(path)
        if actual != entry.get("sha256"):
            failures.append(
                {"path": rel, "error": "checksum mismatch", "expected": entry.get("sha256"), "actual": actual}
            )

    unexpected = []
    if strict:
        ignored = {"COLDVAULT-ARK.json", "COLDVAULT-INDEX.md"}
        for path in root.rglob("*"):
            if path.is_file():
                rel = path.relative_to(root).as_posix()
                if rel not in listed and rel not in ignored:
                    unexpected.append(rel)

    summary = manifest.get("summary", {})
    return {
        "ok": not failures and not unexpected,
        "checked": checked,
        "failures": failures,
        "unexpected": unexpected,
        "archive_complete": bool(summary.get("complete", False)),
        "missing_critical": list(summary.get("missing_critical", [])),
        "missing_recommended": list(summary.get("missing_recommended", [])),
    }
