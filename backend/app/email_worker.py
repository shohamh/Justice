from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import EmailOutbox
from app.db.session import session_scope
from app.services.email import send_email

logger = logging.getLogger(__name__)


def _drain_email_outbox() -> None:
    with session_scope() as session:
        rows = list(
            session.execute(
                select(EmailOutbox)
                .where(EmailOutbox.sent_at.is_(None))
                .order_by(EmailOutbox.created_at)
                .limit(20)
            ).scalars().all()
        )
        for row in rows:
            try:
                ok = send_email(to=row.to_address, subject=row.subject, html_body=row.html_body)
                if ok:
                    row.sent_at = datetime.now(timezone.utc)
                else:
                    row.error = "send failed"
            except Exception as e:
                logger.warning("email worker: failed for %s: %s", row.to_address, e)
                row.error = str(e)
            session.commit()


async def run_email_worker() -> None:
    while True:
        await asyncio.sleep(5)
        try:
            await asyncio.to_thread(_drain_email_outbox)
        except Exception:
            logger.warning("email worker: unhandled error", exc_info=True)
