"""Per-process coalescing of concurrent identical computations.

``SingleFlight.do(key, fn)``: the first caller for ``key`` (the leader) runs
``fn``; a caller with the same key that arrives within ``join_window`` seconds
of the leader's start waits and receives the leader's result. The entry is
removed as soon as the computation ends, so nothing is cached: a call that
starts after the previous one finished computes again. Built on threading
primitives for sync (threadpool) endpoints.

Join window (read-your-writes bound): a caller that arrives later than the
window computes on its own, without replacing the leader's entry. A caller
that refetches right after its own write therefore gets a fresh computation
unless it arrives within the window of a leader that started reading before
the write committed; that residual staleness is bounded by the window
(``JOIN_WINDOW_SECONDS``, 75 ms), which is acceptable for badge counts.

Errors: when ``fn`` raises an ``Exception``, the leader re-raises it and every
waiter raises a fresh ``SingleFlightLeaderError`` chained from it (no shared
exception instance across threads). A ``BaseException`` (KeyboardInterrupt,
SystemExit) propagates only in the leader; waiters get a plain
``SingleFlightLeaderError``.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Hashable

logger = logging.getLogger(__name__)

# Long enough to cover callers that a shell page load fires at the same moment,
# short enough that a refetch issued after a user's own write normally starts a
# new computation instead of joining one that began before the write.
JOIN_WINDOW_SECONDS = 0.075


class SingleFlightLeaderError(RuntimeError):
    """Raised in a waiter when the computation it joined failed."""


class _Call[T]:
    __slots__ = ("done", "started", "waiters", "result", "error", "aborted")

    def __init__(self, started: float) -> None:
        self.done = threading.Event()
        self.started = started
        self.waiters = 0
        self.result: T | None = None
        self.error: Exception | None = None
        self.aborted = False


class SingleFlight[T]:
    def __init__(
        self,
        name: str,
        *,
        join_window: float = JOIN_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._name = name
        self._join_window = join_window
        self._clock = clock
        self._lock = threading.Lock()
        self._calls: dict[Hashable, _Call[T]] = {}

    def waiter_count(self, key: Hashable) -> int:
        """Callers currently waiting on the in-flight computation for ``key``."""
        with self._lock:
            call = self._calls.get(key)
            return call.waiters if call is not None else 0

    def do(self, key: Hashable, fn: Callable[[], T]) -> T:
        with self._lock:
            now = self._clock()
            call = self._calls.get(key)
            if call is not None and now - call.started <= self._join_window:
                call.waiters += 1
                joined: _Call[T] | None = call
            else:
                joined = None
                call = _Call(now)
                if key not in self._calls:
                    self._calls[key] = call
        if joined is not None:
            return self._wait(joined)
        return self._lead(key, call, fn)

    def _wait(self, call: _Call[T]) -> T:
        call.done.wait()
        if call.error is not None:
            raise SingleFlightLeaderError(
                f"shared computation failed: {type(call.error).__name__}"
            ) from call.error
        if call.aborted:
            raise SingleFlightLeaderError("shared computation was aborted")
        return call.result  # type: ignore[return-value]

    def _lead(self, key: Hashable, call: _Call[T], fn: Callable[[], T]) -> T:
        try:
            result = fn()
        except Exception as exc:
            call.error = exc
            raise
        except BaseException:
            call.aborted = True
            raise
        else:
            call.result = result
        finally:
            with self._lock:
                # A late caller computes without registering, so the entry is
                # ours unless this call never registered.
                if self._calls.get(key) is call:
                    del self._calls[key]
                waiters = call.waiters
            call.done.set()
            if waiters:
                logger.debug("single-flight %s: result shared with %d waiters", self._name, waiters)
        return result
