from __future__ import annotations

import os
import threading
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.algorithm import solver

PROFILE_ENV_VAR = "JUSTICE_TEST_SOLVER_PROFILE"
PROFILE_XDIST_WARNING = (
    "WARNING: solver profiling is disabled because pytest-xdist is active; "
    "no profile data was collected. Rerun with -n 0."
)


@dataclass
class SolverProfile:
    durations: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    counts: Counter[str] = field(default_factory=Counter)
    closed: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, phase: str, duration: float) -> None:
        with self._lock:
            self.durations[phase] += duration
            self.counts[phase] += 1

    def close(self) -> None:
        with self._lock:
            self.closed = True


def profiling_requested() -> bool:
    return os.getenv(PROFILE_ENV_VAR) == "1"


def _xdist_active(config: object) -> bool:
    if hasattr(config, "workerinput"):
        return True
    option = getattr(config, "option", None)
    numprocesses = getattr(option, "numprocesses", 0)
    return numprocesses not in (None, 0, "0")


def profiling_enabled(config: object) -> bool:
    return profiling_requested() and not _xdist_active(config)


def profiling_warning(config: object) -> str | None:
    if profiling_requested() and _xdist_active(config):
        return PROFILE_XDIST_WARNING
    return None


@contextmanager
def capture_solver_profile() -> Iterator[SolverProfile]:
    profile = SolverProfile()
    try:
        with solver._capture_profile(profile.record):
            yield profile
    finally:
        profile.close()
