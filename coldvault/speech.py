from __future__ import annotations

import json
import mimetypes
import os
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import ModelConfig


class SpeechError(RuntimeError):
    pass


@dataclass
class SpeechSettings:
    stt: ModelConfig | None = None
    tts: ModelConfig | None = None
    voice: str = "alloy"

    @classmethod
    def from_env(cls) -> "SpeechSettings":
        default_url = os.environ.get("COLDVAULT_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
        api_key = os.environ.get("COLDVAULT_API_KEY", "coldvault-local")
        timeout = int(os.environ.get("COLDVAULT_AUDIO_TIMEOUT", "180"))

        stt_name = os.environ.get("COLDVAULT_STT_MODEL", "").strip()
        tts_name = os.environ.get("COLDVAULT_TTS_MODEL", "").strip()
        stt = None
        tts = None
        if stt_name:
            stt = ModelConfig(
                name=stt_name,
                base_url=os.environ.get("COLDVAULT_STT_BASE_URL", default_url).rstrip("/"),
                api_key=os.environ.get("COLDVAULT_STT_API_KEY", api_key),
                timeout_seconds=timeout,
            ).validate_privacy()
        if tts_name:
            tts = ModelConfig(
                name=tts_name,
                base_url=os.environ.get("COLDVAULT_TTS_BASE_URL", default_url).rstrip("/"),
                api_key=os.environ.get("COLDVAULT_TTS_API_KEY", api_key),
                timeout_seconds=timeout,
            ).validate_privacy()
        return cls(stt=stt, tts=tts, voice=os.environ.get("COLDVAULT_TTS_VOICE", "alloy"))


class LocalSpeechProvider:
    def __init__(self, settings: SpeechSettings):
        self.settings = settings

    def status(self) -> dict:
        return {
            "stt": None if self.settings.stt is None else {
                "configured": True, "model": self.settings.stt.name, "endpoint": self.settings.stt.base_url,
            },
            "tts": None if self.settings.tts is None else {
                "configured": True, "model": self.settings.tts.name, "endpoint": self.settings.tts.base_url,
                "voice": self.settings.voice,
            },
        }

    def transcribe(self, audio_path: Path) -> str:
        config = self.settings.stt
        if config is None:
            raise SpeechError("speech-to-text is not configured; set COLDVAULT_STT_MODEL to an archived local model")
        audio_path = Path(audio_path)
        raw = audio_path.read_bytes()
        if len(raw) > 250 * 1024 * 1024:
            raise SpeechError("audio file exceeds the 250 MB local safety limit")

        boundary = "----ColdVault" + uuid.uuid4().hex
        filename = audio_path.name.replace('"', "_")
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts = []
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{config.name}\r\n".encode("utf-8")
        )
        parts.append(
            (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8") + raw + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)

        request = urllib.request.Request(
            f"{config.base_url}/audio/transcriptions",
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Authorization": f"Bearer {config.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SpeechError(f"local speech-to-text endpoint unavailable or invalid: {exc}") from exc
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise SpeechError(f"unexpected speech-to-text response shape: {payload!r}")
        return text.strip()

    def synthesize(self, text: str, output_path: Path) -> dict:
        config = self.settings.tts
        if config is None:
            raise SpeechError("text-to-speech is not configured; set COLDVAULT_TTS_MODEL to an archived local model")
        text = text.strip()
        if not text:
            raise SpeechError("speech text cannot be empty")
        output_path = Path(output_path)
        fmt = output_path.suffix.lower().lstrip(".") or "wav"
        if fmt not in {"wav", "mp3", "opus", "aac", "flac", "pcm"}:
            raise SpeechError(f"unsupported speech output format: {fmt}")

        body = json.dumps({
            "model": config.name,
            "input": text,
            "voice": self.settings.voice,
            "response_format": fmt,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{config.base_url}/audio/speech",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                audio = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SpeechError(f"local text-to-speech endpoint unavailable: {exc}") from exc
        if not audio:
            raise SpeechError("local text-to-speech endpoint returned an empty audio file")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = output_path.with_suffix(output_path.suffix + ".tmp")
        tmp.write_bytes(audio)
        tmp.replace(output_path)
        return {
            "path": str(output_path),
            "bytes": len(audio),
            "format": fmt,
            "model": config.name,
            "voice": self.settings.voice,
        }
