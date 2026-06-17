from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "email_templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)


def render_notification_email(
    *,
    title: str,
    body: str | None,
    app_url: str,
    frontend_url: str,
    approve_url: str | None = None,
    reject_url: str | None = None,
    soldier_gender: str | None = None,
) -> str:
    open_label = "פתחי במערכת" if soldier_gender == "female" else "פתח במערכת"
    tmpl = _jinja_env.get_template("notification.html.jinja2")
    return tmpl.render(
        title=title,
        body=body,
        app_url=app_url,
        frontend_url=frontend_url,
        approve_url=approve_url,
        reject_url=reject_url,
        open_label=open_label,
    )


def send_email(*, to: str, subject: str, body: str = "", html_body: str | None = None) -> bool:
    """Send an email. Returns False silently when SMTP is not configured."""
    from app.settings import get_settings
    settings = get_settings()
    if not settings.smtp_host:
        logger.debug("SMTP not configured; skipping email to %s", to)
        return False
    try:
        if html_body is not None:
            msg: MIMEMultipart | MIMEText = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.smtp_from or settings.smtp_user
            msg["To"] = to
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        else:
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
