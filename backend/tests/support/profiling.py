from __future__ import annotations

import os
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.algorithm import solver


PROFILE_ENV_VAR = "JUSTICE_TEST_SOLVER_PROFILE"


@dataclass
class SolverProfile:
    durations: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    counts: Counter[str] = field(default_factory=Counter)
    closed: bool = False

    def record(self, phase: str, duration: float) -> None:
        self.durations[phase] += duration
        self.counts[phase] += 1


def profiling_requested() -> bool:
    return os.getenv(PROFILE_ENV_VAR) == "1"


@contextmanager
def capture_solver_profile() -> Iterator[SolverProfile]:
    profile = SolverProfile()
    try:
        with solver._capture_profile(profile.record):
            yield profile
    finally:
        profile.closed = True
