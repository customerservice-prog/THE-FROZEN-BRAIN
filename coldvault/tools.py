from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolPolicy:
    allow_reads: bool = True
    allow_writes: bool = False


class WorkspaceTools:
    def __init__(self, root: Path, policy: ToolPolicy | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.policy = policy or ToolPolicy()

    def _safe(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PermissionError("path escapes ColdVault workspace")
        return candidate

    def list_files(self, relative: str = ".") -> list[str]:
        if not self.policy.allow_reads:
            raise PermissionError("read tools disabled")
        base = self._safe(relative)
        if not base.exists():
            return []
        if base.is_file():
            return [str(base.relative_to(self.root))]
        return sorted(str(p.relative_to(self.root)) for p in base.iterdir())

    def read_text(self, relative: str, max_chars: int = 100_000) -> str:
        if not self.policy.allow_reads:
            raise PermissionError("read tools disabled")
        path = self._safe(relative)
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]

    def write_text(self, relative: str, content: str) -> None:
        if not self.policy.allow_writes:
            raise PermissionError("write tools require explicit enablement")
        path = self._safe(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
