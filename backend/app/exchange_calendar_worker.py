"""Standalone Exchange calendar process: ``python -m app.exchange_calendar_worker``."""

from __future__ import annotations

import logging
import os
import socket
import time
from datetime import UTC, datetime
from uuid import uuid4

from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def main(settings: Settings | None = None) -> int:
    config = settings or get_settings()
    if not config.exchange_calendar_enabled:
        logger.info("Exchange calendar worker disabled")
        return 0

    endpoint, mailbox, username, password = config.require_exchange_calendar_configuration()

    # Keep the optional EWS SDK out of API and disabled-worker imports. In
    # particular, validate configuration before importing or touching EWS.
    from app.db.session import SessionLocal, _engine
    from app.services.exchange_calendar.ews_client import ExchangeCalendarClient, build_account
    from app.services.exchange_calendar.rate_limiter import DatabaseGate, ExchangeRateLimiter
    from app.services.exchange_calendar.worker import ExchangeCalendarWorker, SqlCalendarRepository

    gate = DatabaseGate(
        _engine, rate_per_minute=config.exchange_requests_per_minute
    )
    account = build_account(
        endpoint=endpoint, mailbox=mailbox, username=username, password=password,
        auth_type=config.exchange_auth_type or None,
        permit=ExchangeRateLimiter(gate).permit,
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
    worker = ExchangeCalendarWorker(
        SqlCalendarRepository(SessionLocal, worker_id),
        ExchangeCalendarClient.from_account(account),
    )
    logger.info("Exchange calendar worker started")
    while True:
        try:
            worker.run_once(datetime.now(UTC))
        except KeyboardInterrupt:
            return 0
        except Exception:
            logger.exception("Exchange calendar worker iteration failed")
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
