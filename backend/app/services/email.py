from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_email(*, to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns False silently when SMTP is not configured."""
    from app.settings import get_settings
    settings = get_settings()
    if not settings.smtp_host:
        logger.debug("SMTP not configured; skipping email to %s", to)
        return False
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from or settings.smtp_user
        msg["To"] = to
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return True
    except Exception:
        logger.warning("Failed to send email to %s", to, exc_info=True)
        return False
