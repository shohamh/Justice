"""Standalone Exchange calendar process: ``python -m app.exchange_calendar_worker``."""

from __future__ import annotations

import logging
import os
import socket
import time
from datetime import UTC, datetime
from uuid import uuid4

from app.db.session import SessionLocal, _engine
from app.services.exchange_calendar.ews_client import ExchangeCalendarClient, build_account
from app.services.exchange_calendar.rate_limiter import DatabaseGate, ExchangeRateLimiter
from app.services.exchange_calendar.worker import ExchangeCalendarWorker, SqlCalendarRepository

logger = logging.getLogger(__name__)


def main() -> int:
    endpoint = os.getenv("EXCHANGE_EWS_ENDPOINT")
    mailbox = os.getenv("EXCHANGE_SERVICE_MAILBOX")
    username = os.getenv("EXCHANGE_SERVICE_USERNAME")
    password = os.getenv("EXCHANGE_SERVICE_PASSWORD")
    if not all((endpoint, mailbox, username, password)):
        logger.info("Exchange calendar worker disabled: service configuration is absent")
        return 0
    rate = int(os.getenv("EXCHANGE_MAX_REQUESTS_PER_MINUTE", "200"))
    gate = DatabaseGate(_engine, rate_per_minute=rate)
    account = build_account(
        endpoint=endpoint, mailbox=mailbox, username=username, password=password,
        auth_type=os.getenv("EXCHANGE_AUTH_TYPE") or None,
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
