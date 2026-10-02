"""Renew and fence a durable Exchange job lease while remote work is in flight."""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class LeaseLost(RuntimeError):
    """Raised before an Exchange mutation when this worker no longer owns it."""


class _LeaseGuard:
    def __init__(self, renew: Callable[[], bool]) -> None:
        self.lost = threading.Event()
        self.renew = renew

    def assert_owned(self) -> None:
        if self.lost.is_set():
            raise LeaseLost("Exchange calendar job lease was lost")
        try:
            still_owned = self.renew()
        except Exception:
            still_owned = False
        if not still_owned:
            self.lost.set()
            raise LeaseLost("Exchange calendar job lease was lost")


_current_guard: contextvars.ContextVar[_LeaseGuard | None] = contextvars.ContextVar(
    "exchange_calendar_lease_guard", default=None
)


def assert_lease_owned() -> None:
    """Fence mutations if the renewal thread has lost this job's lease."""
    guard = _current_guard.get()
    if guard is not None:
        guard.assert_owned()


@contextmanager
def maintain_lease(renew: Callable[[], bool], *, interval: float = 60.0) -> Iterator[None]:
    """Renew on a helper thread and make loss visible in the worker context."""
    if interval <= 0:
        raise ValueError("lease renewal interval must be positive")
    stopped = threading.Event()
    guard = _LeaseGuard(renew)

    def renew_until_stopped() -> None:
        while not stopped.wait(interval):
            try:
                guard.assert_owned()
            except LeaseLost:
                return

    token = _current_guard.set(guard)
    thread = threading.Thread(
        target=renew_until_stopped,
        name="exchange-calendar-lease-renewal",
        daemon=True,
    )
    thread.start()
    try:
        guard.assert_owned()
        yield
    finally:
        stopped.set()
        thread.join(timeout=max(1.0, interval + 0.5))
        _current_guard.reset(token)
