from __future__ import annotations

from datetime import date

MAX_REQUEST_SPAN_DAYS = 364  # 1 year minus 1 day


def check_max_span(
    start_date: date,
    end_date: date | None,
    error_cls: type[Exception],
    message: str = "date_range_too_long",
) -> None:
    """Raise error_cls(message) if end_date is set and the range exceeds
    MAX_REQUEST_SPAN_DAYS. Open-ended (end_date=None) ranges are never capped
    here — this guards self-submitted requests, not direct grants."""
    if end_date is not None and (end_date - start_date).days > MAX_REQUEST_SPAN_DAYS:
        raise error_cls(message)
