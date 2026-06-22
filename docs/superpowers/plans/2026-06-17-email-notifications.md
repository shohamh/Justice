# Email Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add email as a second push notification channel — outbox table, Jinja2 HTML templates with logo + action links, in-process asyncio poller, per-type `email_enabled` preference — mirroring the existing Telegram integration.

**Architecture:** When `create_notification()` fires it enqueues an `EmailOutbox` row (alongside the existing `TelegramOutbox` row) if the soldier has a verified email and hasn't disabled the type. A background asyncio task started in FastAPI's lifespan drains the outbox every 5 s via SMTP. Action tokens are the same `TelegramActionToken` rows already used by Telegram — emails render them as clickable URLs.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Jinja2 (new dep), smtplib (stdlib), React + TypeScript

---

## File Map

| File | Change |
|---|---|
| `backend/pyproject.toml` | add `jinja2>=3.1` dependency |
| `backend/app/db/models.py` | add `EmailOutbox` model; add `email_enabled` column to `NotificationPreference` |
| `backend/alembic/versions/0050_email_notifications.py` | migration: new `email_outbox` table + `email_enabled` column |
| `backend/app/email_templates/base.html.jinja2` | **create** RTL base layout with logo, header, footer |
| `backend/app/email_templates/notification.html.jinja2` | **create** extends base; title, body, approve/reject buttons, app link |
| `backend/app/services/email.py` | add `render_notification_email()`; extend `send_email()` with `html_body` param |
| `backend/app/services/notifications.py` | add `_enqueue_email()`; update `ensure_default_prefs()`, `update_preferences()`, `create_notification()`, `_create_notif()` |
| `backend/app/email_worker.py` | **create** async worker that drains `email_outbox` |
| `backend/app/main.py` | add `lifespan` context manager; start email worker |
| `backend/app/routes/notifications.py` | add `email_enabled` to `NotificationPrefOut`; update route serializers |
| `backend/tests/unit/test_email_render.py` | **create** unit tests for `render_notification_email` |
| `backend/tests/integration/test_email_notifications.py` | **create** integration tests for enqueue + preferences |
| `backend/tests/integration/test_notifications_api.py` | update `test_preferences_defaults` to assert `email_enabled: True` |
| `frontend/src/api/notifications.ts` | add `email_enabled` to `NotificationPref`; update `updatePreferences` signature |
| `frontend/src/pages/ProfilePage.tsx` | add email toggle in preferences section; update `handleTogglePref` type |

---

## Task 1: Data model + migration

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/0050_email_notifications.py`

- [ ] **Step 1: Add `EmailOutbox` model and `email_enabled` column to `models.py`**

Open `backend/app/db/models.py`. After the `TelegramOutbox` class (around line 728), add:

```python
class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    to_address: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    html_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
```

In the `NotificationPreference` class (around line 711), add the `email_enabled` column after `push_enabled`:

```python
email_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
```

- [ ] **Step 2: Write the Alembic migration**

Create `backend/alembic/versions/0050_email_notifications.py`:

```python
"""add email_outbox table and email_enabled to notification_preferences

Revision ID: 0050
Revises: 0049
Create Date: 2026-06-17
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("to_address", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_email_outbox_sent_at", "email_outbox", ["sent_at"])
    op.add_column(
        "notification_preferences",
        sa.Column("email_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("notification_preferences", "email_enabled")
    op.drop_index("ix_email_outbox_sent_at", table_name="email_outbox")
    op.drop_table("email_outbox")
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0050_email_notifications.py
git commit -m "feat: add EmailOutbox model, email_enabled to NotificationPreference, migration 0050"
```

---

## Task 2: Jinja2 dependency + email templates + renderer

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/email_templates/base.html.jinja2`
- Create: `backend/app/email_templates/notification.html.jinja2`
- Modify: `backend/app/services/email.py`
- Create: `backend/tests/unit/test_email_render.py`

- [ ] **Step 1: Add Jinja2 to dependencies**

In `backend/pyproject.toml`, add `"jinja2>=3.1"` to the `dependencies` list (after the `holidays` entry):

```toml
dependencies = [
  "fastapi>=0.110",
  "ortools>=9.10",
  "uvicorn[standard]>=0.27",
  "sqlalchemy>=2.0.27",
  "alembic>=1.13",
  "psycopg[binary]>=3.1",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "argon2-cffi>=23.1",
  "python-jose[cryptography]>=3.3",
  "slowapi>=0.1.9",
  "python-multipart>=0.0.9",
  "python-telegram-bot>=21.0",
  "openpyxl>=3.1",
  "holidays>=0.46",
  "jinja2>=3.1",
]
```

Then install it:
```bash
cd backend
pip install -e ".[dev]"
```

Expected: installs without errors.

- [ ] **Step 2: Write the failing render test**

Create `backend/tests/unit/test_email_render.py`:

```python
import pytest
from app.services.email import render_notification_email


def test_render_includes_title():
    html = render_notification_email(
        title="בדיקה",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
    )
    assert "בדיקה" in html


def test_render_includes_body_when_provided():
    html = render_notification_email(
        title="כותרת",
        body="גוף ההודעה",
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
    )
    assert "גוף ההודעה" in html


def test_render_omits_body_when_none():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
    )
    # body paragraph should not appear
    assert "גוף ההודעה" not in html


def test_render_includes_action_buttons_when_urls_provided():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/constraints",
        frontend_url="http://localhost:5173",
        approve_url="http://localhost:5173/action?token=abc",
        reject_url="http://localhost:5173/action?token=xyz",
    )
    assert "http://localhost:5173/action?token=abc" in html
    assert "http://localhost:5173/action?token=xyz" in html
    assert "אשר" in html
    assert "דחה" in html


def test_render_omits_action_buttons_when_urls_absent():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
    )
    assert "אשר" not in html
    assert "דחה" not in html


def test_render_includes_logo_url():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
    )
    assert "favicon.svg" in html


def test_render_gender_aware_open_label_female():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
        soldier_gender="female",
    )
    assert "פתחי במערכת" in html


def test_render_gender_aware_open_label_male():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
        soldier_gender="male",
    )
    assert "פתח במערכת" in html
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd backend
pytest tests/unit/test_email_render.py -v
```

Expected: `ImportError` or `AttributeError` — `render_notification_email` does not exist yet.

- [ ] **Step 4: Create the base email template**

Create `backend/app/email_templates/base.html.jinja2`:

```html
<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{% block title %}לוח כוננות{% endblock %}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">
          <!-- Header -->
          <tr>
            <td style="background:#7c3aed;padding:24px;text-align:center;">
              <img src="{{ frontend_url }}/favicon.svg" width="48" height="48" alt="לוח כוננות" style="display:block;margin:0 auto 8px;">
              <span style="color:#e9d5ff;font-size:18px;font-weight:bold;">לוח כוננות</span>
            </td>
          </tr>
          <!-- Content -->
          <tr>
            <td style="padding:32px 32px 24px;direction:rtl;text-align:right;">
              {% block content %}{% endblock %}
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:16px 32px;border-top:1px solid #e5e7eb;text-align:center;">
              <a href="{{ frontend_url }}" style="color:#7c3aed;text-decoration:none;font-size:12px;">לוח כוננות</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
```

- [ ] **Step 5: Create the notification template**

Create `backend/app/email_templates/notification.html.jinja2`:

```html
{% extends "base.html.jinja2" %}
{% block content %}
<h2 style="margin:0 0 16px;font-size:20px;color:#111827;">{{ title }}</h2>
{% if body %}
<p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">{{ body }}</p>
{% endif %}
{% if approve_url and reject_url %}
<table cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
  <tr>
    <td style="padding-left:8px;">
      <a href="{{ approve_url }}" style="display:inline-block;background:#16a34a;color:#ffffff;padding:10px 20px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:bold;">✅ אשר</a>
    </td>
    <td>
      <a href="{{ reject_url }}" style="display:inline-block;background:#dc2626;color:#ffffff;padding:10px 20px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:bold;">❌ דחה</a>
    </td>
  </tr>
</table>
{% endif %}
<a href="{{ app_url }}" style="color:#7c3aed;font-size:14px;text-decoration:none;">{{ open_label }} ←</a>
{% endblock %}
```

- [ ] **Step 6: Update `services/email.py` — add renderer and html_body to send_email**

Replace the entire content of `backend/app/services/email.py` with:

```python
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
```

- [ ] **Step 7: Run the render tests to verify they pass**

```bash
cd backend
pytest tests/unit/test_email_render.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/app/email_templates/ backend/app/services/email.py backend/tests/unit/test_email_render.py
git commit -m "feat: add Jinja2 email templates and render_notification_email()"
```

---

## Task 3: Email enqueue in notification service

**Files:**
- Modify: `backend/app/services/notifications.py`
- Create: `backend/tests/integration/test_email_notifications.py`

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/integration/test_email_notifications.py`:

```python
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import EmailOutbox, NotificationPreference, NotificationType, Soldier
from app.services.notifications import create_notification
from tests.helpers import auth_headers, create_soldier


def _soldier_with_email(session: Session, personal_number: str, verified: bool = True) -> Soldier:
    s = create_soldier(session, personal_number=personal_number)
    s.email = f"{personal_number}@test.com"
    s.email_verified = verified
    session.flush()
    return s


# --- enqueue behavior ---

def test_email_enqueued_for_verified_soldier(admin_session: Session):
    s = _soldier_with_email(admin_session, "8001001")
    create_notification(admin_session, soldier_id=s.id, type=NotificationType.announcement,
                        title="הודעה")
    admin_session.flush()
    rows = admin_session.query(EmailOutbox).filter_by(to_address=s.email).all()
    assert len(rows) == 1
    assert "הודעה" in rows[0].html_body
    assert rows[0].sent_at is None


def test_email_not_enqueued_for_unverified_soldier(admin_session: Session):
    s = _soldier_with_email(admin_session, "8001002", verified=False)
    create_notification(admin_session, soldier_id=s.id, type=NotificationType.announcement,
                        title="הודעה")
    admin_session.flush()
    rows = admin_session.query(EmailOutbox).filter_by(to_address=s.email).all()
    assert len(rows) == 0


def test_email_not_enqueued_when_no_email(admin_session: Session):
    s = create_soldier(admin_session, personal_number="8001003")
    assert s.email is None
    create_notification(admin_session, soldier_id=s.id, type=NotificationType.announcement,
                        title="הודעה")
    admin_session.flush()
    rows = admin_session.query(EmailOutbox).all()
    assert all(r.to_address != f"8001003@test.com" for r in rows)


def test_email_not_enqueued_when_email_enabled_false(admin_session: Session):
    s = _soldier_with_email(admin_session, "8001004")
    pref = NotificationPreference(
        soldier_id=s.id,
        notification_type=NotificationType.announcement,
        in_app_enabled=True,
        push_enabled=False,
        email_enabled=False,
    )
    admin_session.add(pref)
    admin_session.flush()
    create_notification(admin_session, soldier_id=s.id, type=NotificationType.announcement,
                        title="הודעה")
    admin_session.flush()
    rows = admin_session.query(EmailOutbox).filter_by(to_address=s.email).all()
    assert len(rows) == 0


def test_email_subject_matches_title(admin_session: Session):
    s = _soldier_with_email(admin_session, "8001005")
    create_notification(admin_session, soldier_id=s.id, type=NotificationType.announcement,
                        title="נושא חשוב")
    admin_session.flush()
    row = admin_session.query(EmailOutbox).filter_by(to_address=s.email).one()
    assert row.subject == "נושא חשוב"


# --- preference defaults ---

def test_email_enabled_default_true(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="8001006")
    headers = auth_headers(s)
    resp = client.get("/api/notifications/preferences", headers=headers)
    assert resp.status_code == 200
    for p in resp.json():
        assert p["email_enabled"] is True


def test_update_email_enabled_preference(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="8001007")
    headers = auth_headers(s)
    resp = client.put("/api/notifications/preferences", headers=headers, json={
        "preferences": [{"notification_type": "announcement", "email_enabled": False}]
    })
    assert resp.status_code == 200
    updated = {p["notification_type"]: p for p in resp.json()}
    assert updated["announcement"]["email_enabled"] is False
    # other types unaffected
    assert updated["swap_accepted"]["email_enabled"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend
pytest tests/integration/test_email_notifications.py -v
```

Expected: failures because `EmailOutbox` isn't in the DB yet and `_enqueue_email` doesn't exist.

- [ ] **Step 3: Update `services/notifications.py` — add `_enqueue_email()`**

Add this import at the top of `backend/app/services/notifications.py` (alongside the existing imports):

```python
from app.db.models import (
    ...
    EmailOutbox,  # add to existing import
)
```

Then add the `_enqueue_email` function after `_enqueue_push` (around line 182):

```python
def _enqueue_email(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    title: str,
    body: str | None = None,
    notification_type: NotificationType | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    soldier_gender: str | None = None,
) -> None:
    from app.services.email import render_notification_email
    from app.services.action_tokens import create_token, DEFAULT_ACTION_EXPIRY

    soldier = session.get(Soldier, soldier_id)
    if not soldier or not soldier.email or not soldier.email_verified:
        return

    pref = session.execute(
        select(NotificationPreference).where(
            NotificationPreference.soldier_id == soldier_id,
            NotificationPreference.notification_type == notification_type,
        )
    ).scalar_one_or_none() if notification_type else None
    if pref is not None and not pref.email_enabled:
        return

    approve_url: str | None = None
    reject_url: str | None = None
    if notification_type is not None:
        pair = _action_pair(notification_type)
        if pair and reference_id:
            from app.settings import get_settings
            approve_action, reject_action = pair
            approve_tok = create_token(
                session, soldier_id=soldier_id, action=approve_action,
                resource_type=reference_type, resource_id=reference_id,
                expiry=DEFAULT_ACTION_EXPIRY,
            )
            reject_tok = create_token(
                session, soldier_id=soldier_id, action=reject_action,
                resource_type=reference_type, resource_id=reference_id,
                expiry=DEFAULT_ACTION_EXPIRY,
            )
            base = get_settings().frontend_url.rstrip("/")
            approve_url = f"{base}/action?token={approve_tok}"
            reject_url = f"{base}/action?token={reject_tok}"

    app_url = _frontend_url(notification_type) if notification_type else ""
    html_body = render_notification_email(
        title=title,
        body=body,
        app_url=app_url,
        frontend_url=_get_frontend_base(),
        approve_url=approve_url,
        reject_url=reject_url,
        soldier_gender=soldier_gender,
    )
    session.add(EmailOutbox(
        to_address=soldier.email,
        subject=title,
        html_body=html_body,
    ))


def _get_frontend_base() -> str:
    from app.settings import get_settings
    return get_settings().frontend_url.rstrip("/")
```

- [ ] **Step 4: Wire `_enqueue_email()` into `create_notification()` and `_create_notif()`**

In `create_notification()` (around line 215), add the call after `_enqueue_push(...)`:

```python
    if pref is None or pref.push_enabled:
        soldier = session.get(Soldier, soldier_id)
        _enqueue_push(
            session, soldier_id=soldier_id, text=title,
            notification_type=type,
            reference_type=reference_type,
            reference_id=reference_id,
            soldier_gender=soldier.gender if soldier else None,
        )
    _enqueue_email(
        session, soldier_id=soldier_id, title=title, body=body,
        notification_type=type,
        reference_type=reference_type,
        reference_id=reference_id,
        soldier_gender=soldier.gender if soldier else None,
    )
    return notif
```

In `_create_notif()` (around line 303), add after `_enqueue_push(...)`:

```python
    if pref is None or pref.push_enabled:
        soldier = session.get(Soldier, soldier_id)
        _enqueue_push(
            session, soldier_id=soldier_id, text=title,
            notification_type=type,
            reference_type=reference_type,
            reference_id=reference_id,
            soldier_gender=soldier.gender if soldier else None,
        )
    soldier = session.get(Soldier, soldier_id)
    _enqueue_email(
        session, soldier_id=soldier_id, title=title, body=body,
        notification_type=type,
        reference_type=reference_type,
        reference_id=reference_id,
        soldier_gender=soldier.gender if soldier else None,
    )
```

- [ ] **Step 5: Update `ensure_default_prefs()` — add `email_enabled=True`**

In `ensure_default_prefs()` (around line 326), change the `NotificationPreference(...)` constructor to include `email_enabled=True`:

```python
            session.add(NotificationPreference(
                soldier_id=soldier_id, notification_type=nt,
                in_app_enabled=True, push_enabled=False, email_enabled=True,
            ))
```

- [ ] **Step 6: Update `update_preferences()` — handle `email_enabled`**

In `update_preferences()` (around line 349), add the `email_enabled` line:

```python
            pref.in_app_enabled = pd.get("in_app_enabled", pref.in_app_enabled)
            pref.push_enabled = pd.get("push_enabled", pref.push_enabled)
            pref.email_enabled = pd.get("email_enabled", pref.email_enabled)
```

- [ ] **Step 7: Run integration tests**

```bash
cd backend
pytest tests/integration/test_email_notifications.py -v
```

Expected: all tests PASS.

- [ ] **Step 8: Run full fast suite to check no regressions**

```bash
cd backend
pytest -q
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/notifications.py backend/tests/integration/test_email_notifications.py
git commit -m "feat: add _enqueue_email to notification service with email_enabled preference"
```

---

## Task 4: Background email worker + FastAPI lifespan

**Files:**
- Create: `backend/app/email_worker.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create `email_worker.py`**

Create `backend/app/email_worker.py`:

```python
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
```

- [ ] **Step 2: Add lifespan to `main.py`**

In `backend/app/main.py`, add these imports at the top:

```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
# ... existing imports ...
from app.email_worker import run_email_worker
```

Add the lifespan function before `create_app()`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_email_worker())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

In `create_app()`, pass `lifespan=lifespan` to the `FastAPI(...)` constructor:

```python
def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Justice API", version="0.1.0",
        docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=lifespan,
    )
    # rest unchanged
```

- [ ] **Step 3: Verify the app starts without errors**

```bash
cd backend
python -c "from app.main import create_app; app = create_app(); print('OK')"
```

Expected: prints `OK` with no import errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/email_worker.py backend/app/main.py
git commit -m "feat: add email_worker background task, wire into FastAPI lifespan"
```

---

## Task 5: API schema updates + integration test update

**Files:**
- Modify: `backend/app/routes/notifications.py`
- Modify: `backend/tests/integration/test_notifications_api.py`

- [ ] **Step 1: Update `NotificationPrefOut` and serializers in `routes/notifications.py`**

In `backend/app/routes/notifications.py`, update `NotificationPrefOut`:

```python
class NotificationPrefOut(BaseModel):
    notification_type: str
    in_app_enabled: bool
    push_enabled: bool
    email_enabled: bool
```

Update the serializer in `get_preferences` (around line 154):

```python
    return [NotificationPrefOut(
        notification_type=p.notification_type.value,
        in_app_enabled=p.in_app_enabled,
        push_enabled=p.push_enabled,
        email_enabled=p.email_enabled,
    ) for p in prefs]
```

Update the serializer in `update_preferences` (around line 167):

```python
    return [NotificationPrefOut(
        notification_type=p.notification_type.value,
        in_app_enabled=p.in_app_enabled,
        push_enabled=p.push_enabled,
        email_enabled=p.email_enabled,
    ) for p in prefs]
```

- [ ] **Step 2: Update `test_preferences_defaults` to assert `email_enabled: True`**

In `backend/tests/integration/test_notifications_api.py`, update `test_preferences_defaults`:

```python
def test_preferences_defaults(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001007")
    headers = auth_headers(s)
    resp = client.get("/api/notifications/preferences", headers=headers)
    assert resp.status_code == 200
    prefs = resp.json()
    assert len(prefs) == len(NotificationType)
    for p in prefs:
        assert p["in_app_enabled"] is True
        assert p["push_enabled"] is False
        assert p["email_enabled"] is True
```

- [ ] **Step 3: Run the notifications API tests**

```bash
cd backend
pytest tests/integration/test_notifications_api.py -v
```

Expected: all tests PASS.

- [ ] **Step 4: Run full fast suite to confirm no regressions**

```bash
cd backend
pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/notifications.py backend/tests/integration/test_notifications_api.py
git commit -m "feat: expose email_enabled in NotificationPrefOut API response"
```

---

## Task 6: Frontend updates

**Files:**
- Modify: `frontend/src/api/notifications.ts`
- Modify: `frontend/src/pages/ProfilePage.tsx`

- [ ] **Step 1: Update `NotificationPref` interface and `updatePreferences` in `notifications.ts`**

In `frontend/src/api/notifications.ts`, update the `NotificationPref` interface:

```typescript
export interface NotificationPref {
  notification_type: string;
  in_app_enabled: boolean;
  push_enabled: boolean;
  email_enabled: boolean;
}
```

Update `updatePreferences` to include `email_enabled`:

```typescript
export function updatePreferences(preferences: { notification_type: string; in_app_enabled: boolean; push_enabled: boolean; email_enabled: boolean }[]): Promise<NotificationPref[]> {
  return client.put("/notifications/preferences", { preferences }).then((r) => r.data);
}
```

- [ ] **Step 2: Update `ProfilePage.tsx` — add email toggle**

In `frontend/src/pages/ProfilePage.tsx`, update `handleTogglePref` to accept `email_enabled` as a valid field:

```typescript
  async function handleTogglePref(nt: string, field: "in_app_enabled" | "push_enabled" | "email_enabled") {
    const updated = prefs.map((p) => p.notification_type === nt ? { ...p, [field]: !p[field] } : p);
    setPrefs(updated);
    await updatePreferences(updated.map((p) => ({
      notification_type: p.notification_type,
      in_app_enabled: p.in_app_enabled,
      push_enabled: p.push_enabled,
      email_enabled: p.email_enabled,
    })));
  }
```

In the preferences section (around line 316), update the per-row rendering to add the email toggle. Replace the row rendering block with:

```tsx
        {prefs.map((p) => (
          <div key={p.notification_type} className="flex items-center justify-between py-1 border-b dark:border-gray-600 text-sm">
            <span>{t(`notifications.type_${p.notification_type}`)}</span>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={p.in_app_enabled} onChange={() => handleTogglePref(p.notification_type, "in_app_enabled")} />
                <span className="text-xs">{t("notifications.in_app")}</span>
              </label>
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={p.push_enabled} onChange={() => handleTogglePref(p.notification_type, "push_enabled")} />
                <span className="text-xs">{t("notifications.push")}</span>
              </label>
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={p.email_enabled} onChange={() => handleTogglePref(p.notification_type, "email_enabled")} />
                <span className="text-xs">{t("notifications.email")}</span>
              </label>
            </div>
          </div>
        ))}
```

- [ ] **Step 3: Add the `notifications.email` i18n key**

In `frontend/src/i18n/he.json`, find the `"push": "בטלגרם"` line (around line 759) and add `"email"` after it:

```json
    "in_app": "באפליקציה",
    "push": "בטלגרם",
    "email": "באימייל",
```

- [ ] **Step 4: Run the frontend linter and tests**

```bash
cd frontend
npm run lint
npm test
```

Expected: zero lint warnings, all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/notifications.ts frontend/src/pages/ProfilePage.tsx frontend/src/i18n/he.json
git commit -m "feat: add email_enabled toggle to notification preferences UI"
```

---

## Final check

- [ ] **Run the full backend test suite**

```bash
cd backend
pytest -q
```

Expected: all tests pass, no warnings about missing columns.

- [ ] **Apply the migration and verify the schema**

Start the dev stack (`.\dev.ps1`) and confirm:
1. The app starts without errors
2. Navigate to Profile → Notification Preferences — you should see three columns: **באפליקציה**, **פוש**, **אימייל**
3. Toggle the email checkbox for one type — verify it persists on page reload
