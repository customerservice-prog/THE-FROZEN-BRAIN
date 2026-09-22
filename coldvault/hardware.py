from __future__ import annotations

import os
import platform
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HardwareProfile:
    system: str
    machine: str
    logical_cpus: int
    memory_bytes: int | None
    android: bool
    tier: str

    @property
    def memory_gb(self) -> float | None:
        return None if self.memory_bytes is None else self.memory_bytes / (1024 ** 3)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["memory_gb"] = None if self.memory_gb is None else round(self.memory_gb, 2)
        return data


def _memory_bytes() -> int | None:
    if os.path.exists("/proc/meminfo"):
        try:
            for line in open("/proc/meminfo", "r", encoding="utf-8"):
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        except OSError:
            pass
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        if page_size > 0 and pages > 0:
            return int(page_size * pages)
    except (AttributeError, ValueError, OSError):
        pass
    return None


def _tier(memory: int | None, android: bool) -> str:
    if memory is None:
        return "mobile" if android else "portable"
    gb = memory / (1024 ** 3)
    if gb < 4:
        return "survival"
    if gb < 8:
        return "mobile"
    if gb < 32:
        return "portable"
    if gb < 96:
        return "workstation"
    return "frontier"


def detect_hardware() -> HardwareProfile:
    android = bool(os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"))
    memory = _memory_bytes()
    return HardwareProfile(
        system=platform.system(),
        machine=platform.machine(),
        logical_cpus=os.cpu_count() or 1,
        memory_bytes=memory,
        android=android,
        tier=_tier(memory, android),
    )
