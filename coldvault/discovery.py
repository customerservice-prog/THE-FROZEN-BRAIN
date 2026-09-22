from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import threading
import time
from pathlib import Path


PROTOCOL = "coldvault-discovery-v1"
DEFAULT_PORT = 47821


def load_discovery_key() -> bytes | None:
    literal = os.environ.get("COLDVAULT_DISCOVERY_KEY", "")
    if literal:
        return literal.encode("utf-8")
    path = os.environ.get("COLDVAULT_DISCOVERY_KEY_FILE", "")
    if path:
        raw = Path(path).expanduser().read_bytes().strip()
        return raw or None
    return None


def _canonical(payload: dict) -> bytes:
    unsigned = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_beacon(service_port: int, key: bytes, *, instance: str = "ColdVault", timestamp: int | None = None) -> dict:
    if not key:
        raise ValueError("discovery key cannot be empty")
    payload = {
        "protocol": PROTOCOL,
        "instance": instance[:120],
        "service_port": int(service_port),
        "timestamp": int(time.time() if timestamp is None else timestamp),
    }
    payload["signature"] = hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()
    return payload


def verify_beacon(payload: dict, key: bytes, *, now: int | None = None, max_age_seconds: int = 15) -> bool:
    if not isinstance(payload, dict) or payload.get("protocol") != PROTOCOL or not key:
        return False
    signature = payload.get("signature")
    if not isinstance(signature, str):
        return False
    try:
        timestamp = int(payload["timestamp"])
        service_port = int(payload["service_port"])
    except (KeyError, TypeError, ValueError):
        return False
    if service_port < 1 or service_port > 65535:
        return False
    current = int(time.time() if now is None else now)
    if abs(current - timestamp) > max(1, int(max_age_seconds)):
        return False
    expected = hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


class DiscoveryBeacon:
    def __init__(
        self,
        key: bytes,
        service_port: int,
        *,
        instance: str = "ColdVault",
        discovery_port: int = DEFAULT_PORT,
        target: str = "255.255.255.255",
        interval: float = 3.0,
    ):
        if not key:
            raise ValueError("discovery key cannot be empty")
        self.key = key
        self.service_port = int(service_port)
        self.instance = instance
        self.discovery_port = int(discovery_port)
        self.target = target
        self.interval = max(0.05, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "DiscoveryBeacon":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="coldvault-discovery", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, self.interval * 2.0))

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            while not self._stop.is_set():
                payload = build_beacon(self.service_port, self.key, instance=self.instance)
                raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                try:
                    sock.sendto(raw, (self.target, self.discovery_port))
                except OSError:
                    pass
                self._stop.wait(self.interval)
        finally:
            sock.close()


def discover_servers(
    key: bytes,
    *,
    timeout: float = 2.0,
    discovery_port: int = DEFAULT_PORT,
    max_age_seconds: int = 15,
) -> list[dict]:
    if not key:
        raise ValueError("discovery key cannot be empty")
    timeout = max(0.05, min(float(timeout), 30.0))
    deadline = time.monotonic() + timeout
    found: dict[tuple[str, int], dict] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", int(discovery_port)))
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            sock.settimeout(max(0.01, min(0.25, remaining)))
            try:
                raw, address = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not verify_beacon(payload, key, max_age_seconds=max_age_seconds):
                continue
            host = address[0]
            port = int(payload["service_port"])
            found[(host, port)] = {
                "instance": payload.get("instance", "ColdVault"),
                "host": host,
                "port": port,
                "url": f"http://{host}:{port}",
                "protocol": payload["protocol"],
                "timestamp": int(payload["timestamp"]),
                "authenticated": True,
            }
    finally:
        sock.close()
    return sorted(found.values(), key=lambda item: (item["instance"], item["host"], item["port"]))
