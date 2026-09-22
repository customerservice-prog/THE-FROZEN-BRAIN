from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable

from .knowledge import KnowledgeStore
from .memory import MemoryStore
from .tools import ToolPolicy, WorkspaceTools


class Permission(IntEnum):
    READ = 10
    WRITE = 20
    EXECUTE = 30
    ADMIN = 40


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: Permission
    handler: Callable[[dict[str, Any]], Any]


class ToolRegistry:
    def __init__(self, workspace: Path, memory: MemoryStore, knowledge: KnowledgeStore, permission: Permission = Permission.READ):
        self.workspace = WorkspaceTools(
            workspace,
            ToolPolicy(allow_reads=True, allow_writes=permission >= Permission.WRITE),
        )
        self.memory = memory
        self.knowledge = knowledge
        self.permission = permission
        self._tools: dict[str, ToolSpec] = {}
        self._register_defaults()

    def _register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def _register_defaults(self) -> None:
        self._register(ToolSpec("workspace.list", "List files in the ColdVault workspace.", Permission.READ,
                                lambda a: self.workspace.list_files(str(a.get("path", ".")))))
        self._register(ToolSpec("workspace.read", "Read a UTF-8 text file from the workspace.", Permission.READ,
                                lambda a: self.workspace.read_text(str(a["path"]))))
        self._register(ToolSpec("workspace.write", "Write a UTF-8 text file inside the workspace.", Permission.WRITE,
                                self._write))
        self._register(ToolSpec("memory.search", "Search explicit durable memory.", Permission.READ,
                                lambda a: [m.__dict__ for m in self.memory.search(str(a.get("query", "")), int(a.get("limit", 8)))]))
        self._register(ToolSpec("knowledge.search", "Search locally ingested knowledge.", Permission.READ,
                                lambda a: self.knowledge.search(str(a.get("query", "")), int(a.get("limit", 6)))))
        self._register(ToolSpec("python.run", "Run isolated Python source in the workspace with a timeout.", Permission.EXECUTE,
                                self._python))

    def _write(self, args: dict[str, Any]) -> dict:
        self.workspace.write_text(str(args["path"]), str(args.get("content", "")))
        return {"ok": True}

    def _python(self, args: dict[str, Any]) -> dict:
        code = str(args.get("code", ""))
        timeout = max(1, min(int(args.get("timeout", 10)), 30))
        if len(code) > 100_000:
            raise ValueError("code payload too large")
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-c", code],
            cwd=self.workspace.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return {"returncode": proc.returncode, "stdout": proc.stdout[-100_000:], "stderr": proc.stderr[-100_000:]}

    def list(self) -> list[dict]:
        return [
            {"name": x.name, "description": x.description, "permission": x.permission.name.lower(),
             "enabled": self.permission >= x.permission}
            for x in sorted(self._tools.values(), key=lambda s: s.name)
        ]

    def run(self, name: str, args: dict[str, Any]) -> Any:
        if name not in self._tools:
            raise KeyError(name)
        spec = self._tools[name]
        if self.permission < spec.permission:
            raise PermissionError(f"{name} requires {spec.permission.name.lower()} permission")
        return spec.handler(args)


def permission_from_env() -> Permission:
    raw = os.environ.get("COLDVAULT_TOOL_PERMISSION", "read").strip().lower()
    return {"read": Permission.READ, "write": Permission.WRITE, "execute": Permission.EXECUTE, "admin": Permission.ADMIN}.get(raw, Permission.READ)
