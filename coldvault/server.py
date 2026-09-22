from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .core import ColdVault


class Handler(BaseHTTPRequestHandler):
    vault: ColdVault
    web_root: Path

    def log_message(self, fmt: str, *args) -> None:
        self.vault.db.add_event("http.access", {"message": fmt % args})

    def _json(self, data: dict | list, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 2_000_000:
            raise ValueError("request too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _static(self, name: str) -> None:
        allow = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
        target = allow.get(name)
        if not target:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = self.web_root / target
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        ctype = "text/html; charset=utf-8" if target.endswith(".html") else "application/javascript; charset=utf-8" if target.endswith(".js") else "text/css; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/status":
            self._json(self.vault.status())
            return
        if path == "/api/events":
            self._json(self.vault.db.recent_events(100))
            return
        self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            data = self._read_json()
            if path == "/api/chat":
                self._json(self.vault.chat(str(data.get("message", ""))))
            elif path == "/api/memory":
                memory_id = self.vault.memory.remember(
                    str(data.get("content", "")),
                    kind=str(data.get("kind", "semantic")),
                    source=str(data.get("source", "user")),
                    confidence=float(data.get("confidence", 1.0)),
                    tags=[str(x) for x in data.get("tags", [])],
                )
                self._json({"ok": True, "memory_id": memory_id}, 201)
            elif path == "/api/checkpoint":
                self._json(self.vault.checkpoint(str(data.get("reason", "manual"))), 201)
            elif path == "/api/state":
                allowed = {
                    "active_project", "objective", "subgoals", "known_facts", "hypotheses",
                    "uncertainties", "next_action", "pending_actions", "relevant_files", "commitments",
                }
                changes = {k: v for k, v in data.items() if k in allowed}
                self._json({"ok": True, "state": self.vault.set_state(changes)})
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            self.vault.db.add_event("http.error", {"path": path, "error": repr(exc)})
            self._json({"ok": False, "error": "internal error; see local event log"}, 500)


def serve(vault: ColdVault, host: str = "127.0.0.1", port: int = 7777) -> None:
    repo_root = vault.repo_root
    Handler.vault = vault
    Handler.web_root = repo_root / "web"
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"ColdVault UI: http://{host}:{port}")
    print("Core services are local. Model traffic goes only to the configured provider endpoint.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        vault.checkpoint("server-shutdown")
        server.server_close()
