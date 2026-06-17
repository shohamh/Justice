# Email Notifications Design

**Date:** 2026-06-17  
**Status:** Approved

## Overview

Add email as a second push notification channel alongside Telegram. Uses the same outbox-table pattern already proven for Telegram: when a notification is created, an `EmailOutbox` row is enqueued; a background asyncio task inside the FastAPI process drains the outbox every 5 seconds via SMTP. Emails are HTML (Jinja2), include the app logo, and support one-click approve/reject action links for actionable notification types (reusing the existing `TelegramActionToken` system).

## Decisions

| Question | Decision |
|---|---|
| Delivery architecture | Outbox table + in-process asyncio poller (FastAPI lifespan) |
| Action links | Yes — reuse `TelegramActionToken`, render as `{frontend_url}/action?token=...` |
| Email format | HTML via Jinja2; no plain-text fallback |
| Opt-in | Auto-enabled for any soldier with `email_verified = true` |
| Per-type preference | New `email_enabled` column on `NotificationPreference` (separate from `push_enabled`) |
| Architecture pattern | Minimal parallel addition (mirror Telegram, no new abstraction layer) |

## Section 1: Data Model

### `NotificationPreference` — new column
```
email_enabled: bool  NOT NULL  DEFAULT true
```
`push_enabled` stays as-is (Telegram only). `email_enabled` defaults to `true` so soldiers with a verified email start receiving emails immediately after migration without any manual opt-in.

### New table: `email_outbox`
```
id:           UUID        PK  default gen_random_uuid()
to_address:   Text        NOT NULL
subject:      Text        NOT NULL
html_body:    Text        NOT NULL
created_at:   timestamptz NOT NULL  default now()
sent_at:      timestamptz nullable
error:        Text        nullable
```

Same shape as `telegram_outbox`. No foreign key to `soldiers` — the address is denormalized at enqueue time so a soldier's email change doesn't affect in-flight messages.

One Alembic migration covers both changes.

## Section 2: Notification Service (`services/notifications.py`)

### New function: `_enqueue_email()`
Called alongside `_enqueue_push()` in both `create_notification()` and `_create_notif()`.

```python
def _enqueue_email(
    session, *, soldier_id, title, body,
    notification_type, reference_type, reference_id, soldier_gender,
) -> None:
    soldier = session.get(Soldier, soldier_id)
    if not soldier or not soldier.email or not soldier.email_verified:
        return
    pref = session.execute(
        select(NotificationPreference).where(
            NotificationPreference.soldier_id == soldier_id,
            NotificationPreference.notification_type == notification_type,
        )
    ).scalar_one_or_none()
    if pref is not None and not pref.email_enabled:
        return

    approve_url = reject_url = None
    pair = _action_pair(notification_type)
    if pair and reference_id:
        approve_action, reject_action = pair
        approve_tok = create_token(session, soldier_id=soldier_id, action=approve_action,
                                   resource_type=reference_type, resource_id=reference_id,
                                   expiry=DEFAULT_ACTION_EXPIRY)
        reject_tok = create_token(session, soldier_id=soldier_id, action=reject_action,
                                  resource_type=reference_type, resource_id=reference_id,
                                  expiry=DEFAULT_ACTION_EXPIRY)
        base = get_settings().frontend_url.rstrip("/")
        approve_url = f"{base}/action?token={approve_tok}"
        reject_url = f"{base}/action?token={reject_tok}"

    html_body = render_notification_email(
        title=title, body=body,
        app_url=_frontend_url(notification_type),
        approve_url=approve_url, reject_url=reject_url,
        soldier_gender=soldier_gender,
    )
    session.add(EmailOutbox(
        to_address=soldier.email,
        subject=title,
        html_body=html_body,
    ))
```

### Updates to existing functions
- `ensure_default_prefs()`: add `email_enabled=True` to the `NotificationPreference(...)` constructor call.
- `update_preferences()`: add `pref.email_enabled = pd.get("email_enabled", pref.email_enabled)` alongside the existing `push_enabled` line.

## Section 3: Email Templates

### Location
```
backend/app/email_templates/
  base.html.jinja2          # RTL layout, logo, header, footer
  notification.html.jinja2  # extends base; title, body, action buttons, app link
```

### `base.html.jinja2`
Minimal inline-styled HTML email:
- `dir="rtl"` on `<html>`
- White card on `#f3f4f6` background
- Header: `<img src="{{ frontend_url }}/favicon.svg" width="48" height="48" alt="לוח כוננות">` — the purple scales-of-justice logo
- `{% block content %}` slot
- Footer: app name + link

### `notification.html.jinja2`
Extends base. Renders:
- `{{ title }}` as `<h2>`
- `{{ body }}` as `<p>` (omitted if None)
- Action button row (only when `approve_url` and `reject_url` are set):
  - Green `<a>` button: "✅ אשר" → `approve_url`
  - Red `<a>` button: "❌ דחה" → `reject_url`
- "פתח במערכת" / "פתחי במערכת" `<a>` link → `app_url` (gender-aware label)

### Template renderer — `services/email.py`
New function:
```python
def render_notification_email(*, title, body, app_url,
                               approve_url=None, reject_url=None,
                               soldier_gender=None) -> str:
```
Uses `jinja2.Environment(loader=FileSystemLoader(templates_dir))`.

`send_email()` gets an optional `html_body: str | None = None` parameter. When provided, sends `text/html` MIME; otherwise falls back to existing `text/plain` behavior (backwards compatible).

## Section 4: Background Email Poller

### New file: `backend/app/email_worker.py`
```python
async def run_email_worker() -> None:
    while True:
        await asyncio.sleep(5)
        with session_scope() as session:
            rows = session.execute(
                select(EmailOutbox)
                .where(EmailOutbox.sent_at.is_(None))
                .order_by(EmailOutbox.created_at)
                .limit(20)
            ).scalars().all()
            for row in rows:
                ok = send_email(to=row.to_address, subject=row.subject, html_body=row.html_body)
                if ok:
                    row.sent_at = datetime.now(timezone.utc)
                else:
                    row.error = "send failed"
                session.commit()
```

Rows with `error` set but `sent_at = None` are retried on the next poll cycle (same behavior as `telegram_outbox`).

### FastAPI integration (`main.py`)
Inside the existing `lifespan` context manager:
```python
task = asyncio.create_task(run_email_worker())
yield
task.cancel()
```
No new process, no new entry in `dev.ps1`.

## Section 5: API & Frontend

### Backend schema (`routes/notifications.py`)
`NotificationPreferenceOut` Pydantic model gets `email_enabled: bool` added.  
`PATCH /notifications/preferences` already accepts arbitrary dict keys — no route signature change needed, just the service layer (Section 2) handles the new field.

### Frontend — preferences panel
The per-notification-type preferences table gets a third toggle column labeled **"אימייל"** alongside the existing **"פוש"** (Telegram) column. Uses the same toggle component already in use.

### Frontend — profile/settings page
The soldier's current email address and `email_verified` status should be visible. If unverified, show a prompt to verify (this is the gate for receiving emails). Leverage existing `email_verification` service — no new backend work needed, just surface it in the UI if not already shown.

## Out of Scope

- Plain-text email fallback
- Per-channel toggle at the global level (mute all email vs mute all Telegram)
- Email open/click tracking
- Unsubscribe link in footer (can be added later)
