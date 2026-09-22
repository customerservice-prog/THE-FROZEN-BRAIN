from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path


ALGORITHM = "hmac-sha256"


def load_checkpoint_key() -> bytes | None:
    literal = os.environ.get("COLDVAULT_CHECKPOINT_KEY", "")
    if literal:
        return literal.encode("utf-8")
    path = os.environ.get("COLDVAULT_CHECKPOINT_KEY_FILE", "")
    if path:
        raw = Path(path).expanduser().read_bytes().strip()
        return raw or None
    return None


def seal_checkpoint(canonical_state: str, key: bytes) -> str:
    if not key:
        raise ValueError("checkpoint authentication key cannot be empty")
    return hmac.new(key, canonical_state.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_checkpoint_seal(canonical_state: str, tag: str, key: bytes) -> bool:
    if not key or not isinstance(tag, str):
        return False
    expected = seal_checkpoint(canonical_state, key)
    return hmac.compare_digest(expected, tag)
