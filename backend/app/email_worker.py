from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import EmailOutbox
from app.db.session import session_scope
from app.services.email import send_email

logger = logging.getLogger(__name__)

_BATCH_SIZE = 20


def _claim_next_row(session, attempted: list[uuid.UUID]) -> EmailOutbox | None:
    """Claim one unsent row for this drainer.

    Every uvicorn process runs its own email worker, so several drainers can
    poll the outbox at once. ``FOR UPDATE SKIP LOCKED`` gives each unsent row
    to exactly one drainer: the row lock is held until this drainer commits
    ``sent_at`` (or ``error``), and a concurrent drainer skips the row instead
    of sending it a second time. Once the row is committed as sent, the
    ``sent_at IS NULL`` predicate keeps every later drain away from it.
    """
    stmt = (
        select(EmailOutbox)
        .where(EmailOutbox.sent_at.is_(None))
        .order_by(EmailOutbox.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if attempted:
        stmt = stmt.where(EmailOutbox.id.not_in(attempted))
    return session.execute(stmt).scalars().first()


def _drain_email_outbox() -> None:
    with session_scope() as session:
        # Rows whose send failed stay unsent (sent_at IS NULL) for the next
        # drain; remember them so this drain does not retry them in a loop.
        attempted: list[uuid.UUID] = []
        for _ in range(_BATCH_SIZE):
            row = _claim_next_row(session, attempted)
            if row is None:
                break
            attempted.append(row.id)
            try:
                ok = send_email(to=row.to_address, subject=row.subject, html_body=row.html_body)
                if ok:
                    row.sent_at = datetime.now(timezone.utc)
                else:
                    row.error = "send failed"
            except Exception as e:
                logger.warning("email worker: failed for %s: %s", row.to_address, e)
                row.error = str(e)
            # Commit per row: records the result and releases the claim.
            session.commit()


async def run_email_worker() -> None:
    while True:
        await asyncio.sleep(5)
        try:
            await asyncio.to_thread(_drain_email_outbox)
        except Exception:
            logger.warning("email worker: unhandled error", exc_info=True)
