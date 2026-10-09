"""Per-process coalescing of concurrent identical computations.

``SingleFlight.do(key, fn)``: the first caller for ``key`` runs ``fn``; callers
that arrive with the same key while it runs wait and receive the same result
(or the same exception). The entry is removed as soon as the computation ends,
so nothing is cached: a call that starts after the previous one finished
computes again. Built on threading primitives for sync (threadpool) endpoints.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Hashable


class _Call[T]:
    __slots__ = ("done", "result", "error")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: T | None = None
        self.error: BaseException | None = None


class SingleFlight[T]:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[Hashable, _Call[T]] = {}

    def do(self, key: Hashable, fn: Callable[[], T]) -> T:
        with self._lock:
            call = self._calls.get(key)
            leader = call is None
            if call is None:
                call = _Call()
                self._calls[key] = call
        if not leader:
            call.done.wait()
            if call.error is not None:
                raise call.error
            return call.result  # type: ignore[return-value]
        try:
            call.result = fn()
        except BaseException as exc:
            call.error = exc
            raise
        finally:
            with self._lock:
                del self._calls[key]
            call.done.set()
        return call.result
