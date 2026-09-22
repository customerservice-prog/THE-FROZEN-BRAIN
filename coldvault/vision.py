from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from .config import ModelConfig
from .providers import OpenAICompatibleProvider


class VisionError(RuntimeError):
    pass


class LocalVisionProvider:
    def __init__(self, config: ModelConfig):
        self.config = config.validate_privacy()
        self.provider = OpenAICompatibleProvider(self.config)

    def image_content(self, image_path: Path, prompt: str) -> list[dict]:
        image_path = Path(image_path)
        raw = image_path.read_bytes()
        if len(raw) > 40 * 1024 * 1024:
            raise VisionError("image exceeds the 40 MB local safety limit")
        mime = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        if not mime.startswith("image/"):
            raise VisionError(f"unsupported visual media type: {mime}")
        encoded = base64.b64encode(raw).decode("ascii")
        return [
            {"type": "text", "text": prompt.strip() or "Describe and analyze this image."},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]

    def analyze(self, image_path: Path, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": self.image_content(image_path, prompt)})
        return self.provider.chat(messages, temperature=0.2, max_tokens=1800)
