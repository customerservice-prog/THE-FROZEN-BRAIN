from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator

from ..config import ModelConfig


class ProviderError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    """Talk to a LOCAL OpenAI-compatible chat-completions endpoint using stdlib only."""

    def __init__(self, config: ModelConfig):
        self.config = config

    def chat(self, messages: list[dict], *, temperature: float = 0.4, max_tokens: int = 1400) -> str:
        url = f"{self.config.base_url}/chat/completions"
        payload = json.dumps({
            "model": self.config.name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"local model endpoint unavailable or invalid: {exc}") from exc
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected model response shape: {body!r}") from exc

    def stream_chat(self, messages: list[dict], *, temperature: float = 0.4, max_tokens: int = 1400) -> Iterator[str]:
        """Yield text deltas from a LOCAL OpenAI-compatible SSE chat stream."""
        url = f"{self.config.base_url}/chat/completions"
        payload = json.dumps({
            "model": self.config.name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(f"invalid local model stream event: {data[:200]!r}") from exc
                    try:
                        delta = event["choices"][0].get("delta", {})
                    except (KeyError, IndexError, TypeError) as exc:
                        raise ProviderError(f"unexpected local model stream shape: {event!r}") from exc
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield content
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"local model stream unavailable: {exc}") from exc

    def health(self) -> dict:
        url = f"{self.config.base_url}/models"
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.config.api_key}"})
        try:
            with urllib.request.urlopen(request, timeout=min(5, self.config.timeout_seconds)) as response:
                body = json.loads(response.read().decode("utf-8"))
            return {"ok": True, "endpoint": self.config.base_url, "configured_model": self.config.name, "models": body.get("data", [])[:10]}
        except Exception as exc:
            return {"ok": False, "endpoint": self.config.base_url, "configured_model": self.config.name, "error": str(exc)}
