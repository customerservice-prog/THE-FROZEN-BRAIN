from __future__ import annotations

import hmac
import json
import os
import signal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .core import ColdVault
from .discovery import DiscoveryBeacon, load_discovery_key
from .providers import ProviderError


class Handler(BaseHTTPRequestHandler):
    vault: ColdVault
    web_root: Path
    access_token: str | None = None
    require_auth: bool = False

    def log_message(self, fmt: str, *args) -> None:
        self.vault.db.add_event("http.access", {"message": fmt % args})

    def _authorized(self) -> bool:
        if not self.require_auth:
            return True
        if not self.access_token:
            return False
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.access_token}"
        return hmac.compare_digest(supplied, expected)

    def _require_api_auth(self, path: str) -> bool:
        protected = path.startswith("/api/") or path.startswith("/v1/")
        if not protected or self._authorized():
            return True
        self._json({"ok": False, "error": "authorization required"}, 401)
        return False

    def _json(self, data: dict | list, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _stream_chat_ndjson(self, message: str, conversation_id: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            for event in self.vault.chat_stream(message, conversation_id=conversation_id):
                line = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
                self.wfile.write(line)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.vault.db.add_event("http.stream_disconnected", {"conversation_id": conversation_id})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 2_000_000:
            raise ValueError("request too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _relay_candidates(self, requested_model: str | None):
        candidates = self.vault._provider_candidates("general")
        if requested_model:
            exact = [
                item for item in candidates
                if item[0].model == requested_model or item[0].name == requested_model
            ]
            if exact:
                return exact
        return candidates

    def _relay_chat(self, data: dict) -> None:
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty list")
        requested = str(data.get("model") or "").strip() or None
        temperature = float(data.get("temperature", 0.4))
        max_tokens = int(data.get("max_tokens", 1400))
        failures = []
        for profile, provider in self._relay_candidates(requested):
            try:
                answer = provider.chat(messages, temperature=temperature, max_tokens=max_tokens)
                self.vault.db.add_event(
                    "lan.relay.completed",
                    {"profile": profile.name, "model": profile.model, "failures": failures},
                )
                self._json({
                    "id": "coldvault-local",
                    "object": "chat.completion",
                    "model": profile.model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
                })
                return
            except ProviderError as exc:
                failures.append({"profile": profile.name, "error": str(exc)})
        raise ProviderError("no local provider available for LAN relay: " + "; ".join(x["error"] for x in failures))

    def _relay_stream(self, data: dict) -> None:
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty list")
        requested = str(data.get("model") or "").strip() or None
        temperature = float(data.get("temperature", 0.4))
        max_tokens = int(data.get("max_tokens", 1400))
        failures = []
        chosen = None
        iterator = None
        first = None
        for profile, provider in self._relay_candidates(requested):
            try:
                candidate = provider.stream_chat(messages, temperature=temperature, max_tokens=max_tokens)
                first = next(candidate)
                chosen = profile
                iterator = candidate
                break
            except (ProviderError, StopIteration) as exc:
                failures.append({"profile": profile.name, "error": str(exc) or "stream ended without text"})
        if chosen is None or iterator is None or first is None:
            raise ProviderError("no local provider available for LAN relay: " + "; ".join(x["error"] for x in failures))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        def send_delta(text: str) -> None:
            payload = json.dumps({
                "id": "coldvault-local",
                "object": "chat.completion.chunk",
                "model": chosen.model,
                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
            }, ensure_ascii=False)
            self.wfile.write(("data: " + payload + "\n\n").encode("utf-8"))
            self.wfile.flush()

        try:
            send_delta(first)
            for chunk in iterator:
                send_delta(chunk)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.vault.db.add_event(
                "lan.relay.completed",
                {"profile": chosen.name, "model": chosen.model, "stream": True, "failures": failures},
            )
        except (BrokenPipeError, ConnectionResetError):
            self.vault.db.add_event("lan.relay.disconnected", {"profile": chosen.name, "model": chosen.model})

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
        if target.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        elif target.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        else:
            ctype = "text/css; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if not self._require_api_auth(path):
            return
        if path == "/v1/models":
            self._json({
                "object": "list",
                "data": [
                    {
                        "id": profile.model,
                        "object": "model",
                        "owned_by": "coldvault-local",
                        "profile": profile.name,
                    }
                    for profile in self.vault.models.profiles
                    if profile.enabled
                ],
            })
        elif path == "/api/status":
            self._json(self.vault.status())
        elif path == "/api/events":
            self._json(self.vault.db.recent_events(100))
        elif path == "/api/conversations":
            self._json(self.vault.conversations.list())
        elif path == "/api/history":
            conversation_id = query.get("conversation_id", ["default"])[0]
            self._json(self.vault.conversations.history(conversation_id, limit=100))
        elif path == "/api/projects":
            self._json(self.vault.projects.list())
        elif path == "/api/tasks":
            project = query.get("project", [""])[0]
            self._json(self.vault.projects.tasks(project) if project else [])
        elif path == "/api/tools":
            self._json(self.vault.tools.list())
        elif path == "/api/reminders":
            self._json(self.vault.prospective.list("pending", limit=100))
        elif path == "/api/jobs":
            self._json(self.vault.jobs.list(limit=100))
        else:
            self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not self._require_api_auth(path):
            return
        try:
            data = self._read_json()
            if path == "/v1/chat/completions":
                if bool(data.get("stream", False)):
                    self._relay_stream(data)
                else:
                    self._relay_chat(data)
            elif path == "/api/chat":
                self._json(self.vault.chat(
                    str(data.get("message", "")),
                    conversation_id=str(data.get("conversation_id", "default")),
                ))
            elif path == "/api/chat/stream":
                self._stream_chat_ndjson(
                    str(data.get("message", "")),
                    str(data.get("conversation_id", "default")),
                )
            elif path == "/api/think":
                self._json(self.vault.deep_think(
                    str(data.get("message", "")),
                    conversation_id=str(data.get("conversation_id", "default")),
                    attempts=int(data.get("attempts", 2)),
                ))
            elif path == "/api/conversations":
                conversation_id = self.vault.conversations.create(str(data.get("title", "New conversation")))
                self._json({"ok": True, "conversation_id": conversation_id}, 201)
            elif path == "/api/reminders":
                reminder_id = self.vault.prospective.create(
                    str(data.get("content", "")),
                    str(data.get("due_at", "")),
                    source=str(data.get("source", "user")),
                )
                self._json({"ok": True, "id": reminder_id}, 201)
            elif path == "/api/reminder-status":
                self.vault.prospective.set_status(
                    str(data.get("id", "")),
                    str(data.get("status", "")),
                )
                self._json({"ok": True})
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
            elif path == "/api/tasks":
                task = self.vault.projects.add_task(
                    str(data.get("project", "")),
                    str(data.get("title", "")),
                    str(data.get("details", "")),
                )
                self._json({"ok": True, "task": task}, 201)
            elif path == "/api/task-status":
                self.vault.projects.set_task_status(str(data.get("task_id", "")), str(data.get("status", "")))
                self._json({"ok": True})
            elif path == "/api/tools/run":
                arguments = data.get("arguments", {})
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
                self._json(self.vault.run_tool(str(data.get("name", "")), arguments))
            elif path == "/api/job-retry":
                self._json(self.vault.retry_tool_job(str(data.get("id", ""))))
            elif path == "/api/job-cancel":
                self._json(self.vault.cancel_tool_job(str(data.get("id", ""))))
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except (ValueError, TypeError, json.JSONDecodeError, KeyError, PermissionError) as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            self.vault.db.add_event("http.error", {"path": path, "error": repr(exc)})
            self._json({"ok": False, "error": "internal error; see local event log"}, 500)


def serve(vault: ColdVault, host: str = "127.0.0.1", port: int = 7777) -> None:
    Handler.vault = vault
    Handler.web_root = vault.repo_root / "web"

    loopback = host in {"127.0.0.1", "localhost", "::1"}
    access_token = os.environ.get("COLDVAULT_ACCESS_TOKEN", "").strip()
    if not loopback and not access_token:
        raise ValueError(
            "refusing non-loopback bind without COLDVAULT_ACCESS_TOKEN; "
            "set a strong local token before exposing ColdVault on an offline LAN"
        )
    Handler.access_token = access_token or None
    Handler.require_auth = not loopback

    server = ThreadingHTTPServer((host, port), Handler)
    discovery_key = load_discovery_key()
    beacon = None
    if discovery_key and not loopback:
        discovery_port = int(os.environ.get("COLDVAULT_DISCOVERY_PORT", "47821"))
        beacon = DiscoveryBeacon(
            discovery_key,
            port,
            instance=str(vault.identity.get("name", "ColdVault")),
            discovery_port=discovery_port,
        ).start()

    previous_sigterm = None
    if hasattr(signal, "SIGTERM"):
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def _checkpoint_signal(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, _checkpoint_signal)

    print(f"ColdVault UI: http://{host}:{port}")
    print("Core services are local. Model traffic goes only to the configured local/LAN provider endpoint by default.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        vault.checkpoint("server-shutdown")
        server.server_close()
        if beacon is not None:
            beacon.stop()
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
