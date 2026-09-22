from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .hardware import detect_hardware


@dataclass(frozen=True)
class SurvivalSelection:
    tier: str
    ram_bytes: int | None
    budget_bytes: int | None
    model_path: str | None
    model_bytes: int | None
    context_tokens: int
    candidates_seen: int
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def _context_for_ram(memory_bytes: int | None) -> int:
    if memory_bytes is None:
        return 2048
    gb = memory_bytes / (1024 ** 3)
    if gb < 4:
        return 2048
    if gb < 6:
        return 3072
    if gb < 10:
        return 4096
    if gb < 20:
        return 8192
    return 16384


def _budget_for_ram(memory_bytes: int | None) -> int | None:
    if memory_bytes is None:
        return None
    reserve = int(1.15 * 1024 ** 3)
    if memory_bytes <= reserve:
        return max(64 * 1024 ** 2, int(memory_bytes * 0.28))
    gb = memory_bytes / (1024 ** 3)
    ratio = 0.38 if gb < 4 else 0.46 if gb < 8 else 0.54
    return max(256 * 1024 ** 2, min(int(memory_bytes * ratio), memory_bytes - reserve))


def select_survival_model(model_dir: Path, memory_bytes: int | None = None) -> SurvivalSelection:
    model_dir = Path(model_dir).expanduser().resolve()
    hardware = detect_hardware()
    memory = hardware.memory_bytes if memory_bytes is None else int(memory_bytes)
    budget = _budget_for_ram(memory)
    context = _context_for_ram(memory)

    if not model_dir.is_dir():
        return SurvivalSelection(
            tier=hardware.tier,
            ram_bytes=memory,
            budget_bytes=budget,
            model_path=None,
            model_bytes=None,
            context_tokens=context,
            candidates_seen=0,
            reason=f"model directory does not exist: {model_dir}",
        )

    candidates = []
    for path in model_dir.rglob("*.gguf"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        candidates.append((size, path))
    candidates.sort(key=lambda item: item[0])

    if not candidates:
        return SurvivalSelection(
            tier=hardware.tier,
            ram_bytes=memory,
            budget_bytes=budget,
            model_path=None,
            model_bytes=None,
            context_tokens=context,
            candidates_seen=0,
            reason="no GGUF models found",
        )

    if budget is None:
        size, path = candidates[0]
        return SurvivalSelection(
            tier=hardware.tier,
            ram_bytes=memory,
            budget_bytes=None,
            model_path=str(path),
            model_bytes=size,
            context_tokens=context,
            candidates_seen=len(candidates),
            reason="RAM could not be measured; selected the smallest available GGUF conservatively",
        )

    fitting = [(size, path) for size, path in candidates if size <= budget]
    if not fitting:
        smallest_size, smallest_path = candidates[0]
        return SurvivalSelection(
            tier=hardware.tier,
            ram_bytes=memory,
            budget_bytes=budget,
            model_path=None,
            model_bytes=None,
            context_tokens=context,
            candidates_seen=len(candidates),
            reason=(
                f"no GGUF fits conservative budget; smallest is {smallest_size} bytes at {smallest_path}"
            ),
        )

    size, path = fitting[-1]
    return SurvivalSelection(
        tier=hardware.tier,
        ram_bytes=memory,
        budget_bytes=budget,
        model_path=str(path),
        model_bytes=size,
        context_tokens=context,
        candidates_seen=len(candidates),
        reason="selected the largest GGUF that fits the conservative RAM budget",
    )
