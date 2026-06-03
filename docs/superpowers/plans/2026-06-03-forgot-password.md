# Forgot Password Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let soldiers reset their password via a one-time link delivered to Telegram or email, with full email infrastructure (SMTP settings + email service) added but left unconfigured.

**Architecture:** Three new backend endpoints handle channel discovery, link dispatch, and token redemption. A dedicated `password_reset_tokens` table stores 15-minute one-time tokens. Email is sent via `smtplib`; Telegram via the existing `TelegramOutbox` queue. Frontend adds `/forgot-password` and `/reset-password` pages, plus email field in profile/registration.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, smtplib, React, TypeScript, react-router-dom v6.

---

## File Map

| File | Change |
|---|---|
| `backend/alembic/versions/0036_forgot_password.py` | Migration: email on soldiers, password_reset_tokens table |
| `backend/app/db/models.py` | Add `email` to `Soldier`, add `PasswordResetToken` model |
| `backend/app/settings.py` | Add 5 SMTP fields (all default empty) |
| `backend/app/services/email.py` | New: `send_email()` — no-ops when SMTP unconfigured |
| `backend/app/services/password_reset.py` | New: `create_and_send_reset_token()`, `redeem_reset_token()` |
| `backend/app/routes/auth.py` | Add 3 new endpoints: check-channels, send, redeem |
| `backend/app/routes/soldiers.py` | Rename `_can_see_gender` → `_can_see_private_fields`; add `email` to `SoldierOut` + `_out()` |
| `backend/app/routes/me.py` | Add `email` to `MeResponse` |
| `backend/tests/integration/test_forgot_password.py` | Integration tests |
| `frontend/src/api/auth.ts` | Add `checkForgotPasswordChannels()`, `sendForgotPassword()`, `resetPassword()`, add `email` to `Me` |
| `frontend/src/pages/ForgotPasswordPage.tsx` | New: two-step forgot password page |
| `frontend/src/pages/ResetPasswordPage.tsx` | New: reset password form |
| `frontend/src/pages/LoginPage.tsx` | Add "שכחתי סיסמה" link |
| `frontend/src/App.tsx` | Add `/forgot-password` and `/reset-password` routes |
| `frontend/src/pages/ProfilePage.tsx` | Add email field (editable by self) |
| `frontend/src/pages/RegisterPage.tsx` | Add email field in step 2 |
| `frontend/src/components/SoldierEditModal.tsx` | Add email field (admin only) |
| `frontend/src/i18n/he.json` | Add `forgot_password.*` and `reset_password.*` keys |

---

## Task 1: Migration and models

**Files:**
- Create: `backend/alembic/versions/0036_forgot_password.py`
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Create the migration file**

```python
"""forgot password: email on soldiers, password_reset_tokens table

Revision ID: 0036
Revises: 0035
Create Date: 2026-06-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("soldiers", sa.Column("email", sa.Text(), nullable=True))

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["soldier_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_prt_soldier"),
    )
    op.create_index("ix_password_reset_tokens_token", "password_reset_tokens", ["token"], unique=True)
    op.create_index("ix_password_reset_tokens_soldier", "password_reset_tokens", ["soldier_id"])


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_soldier", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_token", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_column("soldiers", "email")
```

- [ ] **Step 2: Apply migration**

```bash
cd backend
uv run alembic upgrade head
```

Expected: ends with `Running upgrade 0035 -> 0036`.

- [ ] **Step 3: Add email to Soldier model**

In `backend/app/db/models.py`, find the `Soldier` class and add after `phone`:

```python
email: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
```

- [ ] **Step 4: Add PasswordResetToken model**

At the end of `backend/app/db/models.py`, add:

```python
class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 5: Verify models import**

```bash
cd backend
python -c "from app.db.models import PasswordResetToken, Soldier; print(Soldier.email)"
```

Expected: prints the column descriptor without error.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/0036_forgot_password.py backend/app/db/models.py
git commit -m "feat: migration 0036 — email on soldiers, password_reset_tokens table"
```

---

## Task 2: SMTP settings and email service

**Files:**
- Modify: `backend/app/settings.py`
- Create: `backend/app/services/email.py`

- [ ] **Step 1: Add SMTP fields to Settings**

In `backend/app/settings.py`, add after `frontend_url`:

```python
smtp_host: str = Field(default="", alias="SMTP_HOST")
smtp_port: int = Field(default=587, alias="SMTP_PORT")
smtp_user: str = Field(default="", alias="SMTP_USER")
smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
smtp_from: str = Field(default="", alias="SMTP_FROM")
```

- [ ] **Step 2: Create email service**

Create `backend/app/services/email.py`:

```python
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
```

- [ ] **Step 3: Verify import**

```bash
cd backend
python -c "from app.services.email import send_email; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/settings.py backend/app/services/email.py
git commit -m "feat: SMTP settings and email service (unconfigured by default)"
```

---

## Task 3: Password reset service

**Files:**
- Create: `backend/app/services/password_reset.py`
- Create: `backend/tests/integration/test_forgot_password.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/integration/test_forgot_password.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.db.models import PasswordResetToken, Soldier, TelegramLink
from app.services import password_reset as svc
from tests.helpers import create_soldier


def _link_telegram(session: Session, soldier_id: uuid.UUID, chat_id: int) -> None:
    link = TelegramLink(
        soldier_id=soldier_id,
        telegram_chat_id=chat_id,
        is_verified=True,
        notifications_enabled=True,
    )
    session.add(link)
    session.flush()


def test_available_channels_telegram_only(admin_session: Session):
    s = create_soldier(admin_session, personal_number="PR001")
    _link_telegram(admin_session, s.id, 9001)
    admin_session.flush()

    channels = svc.available_channels(admin_session, personal_number="PR001")
    assert "telegram" in channels
    assert "email" not in channels


def test_available_channels_email_only(admin_session: Session):
    s = create_soldier(admin_session, personal_number="PR002")
    s.email = "test@example.com"
    admin_session.flush()

    channels = svc.available_channels(admin_session, personal_number="PR002")
    assert "email" in channels
    assert "telegram" not in channels


def test_available_channels_none(admin_session: Session):
    create_soldier(admin_session, personal_number="PR003")
    admin_session.flush()

    channels = svc.available_channels(admin_session, personal_number="PR003")
    assert channels == []


def test_available_channels_unknown_personal_number(admin_session: Session):
    channels = svc.available_channels(admin_session, personal_number="UNKNOWN999")
    assert channels == []


def test_create_token_invalidates_previous(admin_session: Session):
    from sqlalchemy import select
    s = create_soldier(admin_session, personal_number="PR004")
    admin_session.flush()

    token1 = svc._create_reset_token(admin_session, soldier=s, channel="email")
    admin_session.flush()
    token2 = svc._create_reset_token(admin_session, soldier=s, channel="email")
    admin_session.flush()

    old = admin_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == token1)
    ).scalar_one()
    assert old.used_at is not None  # invalidated
    assert token1 != token2


def test_redeem_token_updates_password(admin_session: Session):
    from app.auth.password import verify_password
    s = create_soldier(admin_session, personal_number="PR005")
    s.email = "pr005@example.com"
    admin_session.flush()

    token = svc._create_reset_token(admin_session, soldier=s, channel="email")
    admin_session.flush()

    result = svc.redeem_reset_token(admin_session, token=token, new_password="NewPass1234!")
    admin_session.flush()

    assert result == "ok"
    assert verify_password("NewPass1234!", s.password_hash)
    assert s.must_change_password is False


def test_redeem_token_expired(admin_session: Session):
    from sqlalchemy import select
    s = create_soldier(admin_session, personal_number="PR006")
    admin_session.flush()

    token_str = "expiredtoken0000000000000000000"
    row = PasswordResetToken(
        soldier_id=s.id,
        token=token_str,
        channel="email",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    admin_session.add(row)
    admin_session.flush()

    result = svc.redeem_reset_token(admin_session, token=token_str, new_password="NewPass1234!")
    assert result == "token_expired"


def test_redeem_token_already_used(admin_session: Session):
    s = create_soldier(admin_session, personal_number="PR007")
    admin_session.flush()

    token = svc._create_reset_token(admin_session, soldier=s, channel="email")
    admin_session.flush()

    svc.redeem_reset_token(admin_session, token=token, new_password="NewPass1234!")
    admin_session.flush()
    result = svc.redeem_reset_token(admin_session, token=token, new_password="AnotherPass1234!")
    assert result == "token_invalid"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
uv run pytest tests/integration/test_forgot_password.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'app.services.password_reset'`

- [ ] **Step 3: Implement password_reset service**

Create `backend/app/services/password_reset.py`:

```python
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.models import PasswordResetToken, Soldier, TelegramLink, TelegramOutbox
from app.services.email import send_email
from app.services.soldiers import PasswordPolicyError, validate_password

_TOKEN_EXPIRY = timedelta(minutes=15)


def available_channels(session: Session, *, personal_number: str) -> list[str]:
    """Return list of available delivery channels for a personal number.
    Returns [] if soldier not found (no enumeration)."""
    soldier = session.execute(
        select(Soldier).where(Soldier.personal_number == personal_number, Soldier.left_at.is_(None))
    ).scalar_one_or_none()
    if soldier is None:
        return []
    channels: list[str] = []
    link = session.execute(
        select(TelegramLink).where(
            TelegramLink.soldier_id == soldier.id,
            TelegramLink.is_verified == True,  # noqa: E712
            TelegramLink.telegram_chat_id.isnot(None),
        )
    ).scalar_one_or_none()
    if link is not None:
        channels.append("telegram")
    if soldier.email:
        channels.append("email")
    return channels


def _create_reset_token(session: Session, *, soldier: Soldier, channel: str) -> str:
    """Invalidate existing tokens and create a new one. Returns the token string."""
    now = datetime.now(timezone.utc)
    existing = session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.soldier_id == soldier.id,
            PasswordResetToken.used_at.is_(None),
        )
    ).scalars().all()
    for row in existing:
        row.used_at = now

    token = secrets.token_hex(16)  # 32 hex chars
    row = PasswordResetToken(
        soldier_id=soldier.id,
        token=token,
        channel=channel,
        expires_at=now + _TOKEN_EXPIRY,
    )
    session.add(row)
    session.flush()
    return token


def create_and_send(session: Session, *, personal_number: str, channel: str) -> None:
    """Create a reset token and dispatch it. Silently no-ops if soldier not found."""
    from app.settings import get_settings
    soldier = session.execute(
        select(Soldier).where(Soldier.personal_number == personal_number, Soldier.left_at.is_(None))
    ).scalar_one_or_none()
    if soldier is None:
        return
    channels = available_channels(session, personal_number=personal_number)
    if channel not in channels:
        return

    token = _create_reset_token(session, soldier=soldier, channel=channel)
    settings = get_settings()
    reset_url = f"{settings.frontend_url.rstrip('/')}/reset-password?token={token}"

    if channel == "telegram":
        link = session.execute(
            select(TelegramLink).where(
                TelegramLink.soldier_id == soldier.id,
                TelegramLink.is_verified == True,  # noqa: E712
                TelegramLink.telegram_chat_id.isnot(None),
            )
        ).scalar_one_or_none()
        if link:
            session.add(TelegramOutbox(
                telegram_chat_id=link.telegram_chat_id,
                message_text=f"קישור לאיפוס סיסמה (תקף ל-15 דקות):\n{reset_url}",
            ))
    elif channel == "email" and soldier.email:
        send_email(
            to=soldier.email,
            subject="איפוס סיסמה — ניהול תורנויות",
            body=f"קישור לאיפוס סיסמה (תקף ל-15 דקות):\n{reset_url}\n\nאם לא ביקשת איפוס סיסמה, התעלם מהודעה זו.",
        )


def redeem_reset_token(session: Session, *, token: str, new_password: str) -> str:
    """Validate token and update password. Returns 'ok', 'token_invalid', or 'token_expired'."""
    now = datetime.now(timezone.utc)
    row = session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == token,
            PasswordResetToken.used_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        return "token_invalid"
    if row.expires_at <= now:
        return "token_expired"
    try:
        validate_password(new_password)
    except PasswordPolicyError:
        return "password_too_short"
    soldier = session.get(Soldier, row.soldier_id)
    if soldier is None:
        return "token_invalid"
    soldier.password_hash = hash_password(new_password)
    soldier.must_change_password = False
    row.used_at = now
    session.flush()
    return "ok"
```

- [ ] **Step 4: Run tests**

```bash
cd backend
uv run pytest tests/integration/test_forgot_password.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/password_reset.py backend/tests/integration/test_forgot_password.py
git commit -m "feat: password_reset service — create/send/redeem one-time reset tokens"
```

---

## Task 4: Auth route endpoints

**Files:**
- Modify: `backend/app/routes/auth.py`

- [ ] **Step 1: Add request/response models to auth.py**

After the existing `RegisterRequest` class in `backend/app/routes/auth.py`, add:

```python
class ForgotPasswordCheckRequest(BaseModel):
    personal_number: str = Field(min_length=1, max_length=20)


class ForgotPasswordChannelsResponse(BaseModel):
    channels: list[str]


class ForgotPasswordSendRequest(BaseModel):
    personal_number: str = Field(min_length=1, max_length=20)
    channel: str = Field(pattern="^(telegram|email)$")


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=100)
    new_password: str = Field(min_length=1, max_length=200)
```

- [ ] **Step 2: Add the import for password_reset service**

At the top of `backend/app/routes/auth.py`, add after the existing service imports:

```python
from app.services import password_reset as pwd_reset_svc
```

- [ ] **Step 3: Add the three new endpoints**

At the end of `backend/app/routes/auth.py`, add:

```python
@router.post("/forgot-password", response_model=ForgotPasswordChannelsResponse)
@limiter.limit(get_settings().login_rate_limit)
def forgot_password_check(
    body: Annotated[ForgotPasswordCheckRequest, Body()],
    request: Request,
    session: Session = Depends(get_session),
) -> ForgotPasswordChannelsResponse:
    channels = pwd_reset_svc.available_channels(session, personal_number=body.personal_number)
    return ForgotPasswordChannelsResponse(channels=channels)


@router.post("/forgot-password/send", status_code=200)
@limiter.limit(get_settings().login_rate_limit)
def forgot_password_send(
    body: Annotated[ForgotPasswordSendRequest, Body()],
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    pwd_reset_svc.create_and_send(session, personal_number=body.personal_number, channel=body.channel)
    session.commit()
    return {}


@router.post("/reset-password", status_code=200)
def reset_password(
    body: ResetPasswordRequest,
    session: Session = Depends(get_session),
) -> dict:
    result = pwd_reset_svc.redeem_reset_token(session, token=body.token, new_password=body.new_password)
    if result == "ok":
        session.commit()
        return {}
    session.rollback()
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
```

- [ ] **Step 4: Test the endpoints with curl**

```bash
# Start the dev server or use docker exec
curl -s -X POST http://localhost:8000/api/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"personal_number":"9999999"}'
```

Expected: `{"channels":[]}`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/auth.py
git commit -m "feat: forgot-password and reset-password auth endpoints"
```

---

## Task 5: Soldiers and Me route — email field + rename private field check

**Files:**
- Modify: `backend/app/routes/soldiers.py`
- Modify: `backend/app/routes/me.py`

- [ ] **Step 1: Rename `_can_see_gender` to `_can_see_private_fields` in soldiers.py**

In `backend/app/routes/soldiers.py`:
1. Rename the function definition from `_can_see_gender` to `_can_see_private_fields`
2. Update the docstring: `"""Private fields (gender, email) visible to self, commanders in chain, DMs, admins."""`
3. Replace all 3 call sites of `_can_see_gender(` with `_can_see_private_fields(`

- [ ] **Step 2: Add email to SoldierOut**

In `SoldierOut`, add after `telegram_linked`:

```python
email: str | None = None
```

- [ ] **Step 3: Update `_out()` to include email**

Change the function signature and return:

```python
def _out(s: Soldier, *, include_gender: bool = False, include_private: bool = False, telegram_linked: bool = False) -> SoldierOut:
    return SoldierOut(
        ...
        gender=s.gender if include_private else None,
        ...
        telegram_linked=telegram_linked,
        email=s.email if include_private else None,
    )
```

Then update all 3 call sites that pass `include_gender=...` to pass `include_private=_can_see_private_fields(session, user, s)` instead. The existing `include_gender` parameter should be removed (it's now `include_private`).

The 3 call sites are:
- In `get_soldier` (line ~379): `_out(s, include_gender=_can_see_gender(...), ...)` → `_out(s, include_private=_can_see_private_fields(session, user, s), ...)`
- In `update_profile` (line ~413): same pattern
- In `list_soldiers` (lines ~233, 244): these don't pass `include_gender` — leave as-is (no private fields in list view)

- [ ] **Step 4: Add email to MeResponse in me.py**

In `backend/app/routes/me.py`, add `email: str | None = None` to `MeResponse`, and add `email=user.email,` to the `return MeResponse(...)` call.

- [ ] **Step 5: Verify imports compile**

```bash
cd backend
python -c "from app.routes.soldiers import router; from app.routes.me import router; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Run existing soldier tests**

```bash
cd backend
uv run pytest tests/integration/test_soldiers_api.py -v 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/soldiers.py backend/app/routes/me.py
git commit -m "feat: add email to soldiers/me routes, rename _can_see_gender to _can_see_private_fields"
```

---

## Task 6: Frontend API and types

**Files:**
- Modify: `frontend/src/api/auth.ts`

- [ ] **Step 1: Add email to Me type and add three new API functions**

In `frontend/src/api/auth.ts`, add `email?: string | null` to the `Me` interface:

```typescript
export interface Me {
  id: string;
  personal_number: string;
  full_name: string;
  role: "soldier" | "commander" | "duty_manager" | "admin";
  must_change_password: boolean;
  hierarchy_node_id: string | null;
  telegram_linked: boolean;
  telegram_required: boolean;
  phone?: string | null;
  gender?: string | null;
  email?: string | null;
  is_officer?: boolean | null;
  rank?: string | null;
  bahad1_graduate?: boolean;
  enlistment_date?: string | null;
  mandatory_end_date?: string | null;
  discharge_date?: string | null;
  last_mitvahim_date?: string | null;
  last_alal_date?: string | null;
}
```

Then add three new exported functions at the end of the file:

```typescript
export async function checkForgotPasswordChannels(personal_number: string): Promise<string[]> {
  const r = await api.post<{ channels: string[] }>("/auth/forgot-password", { personal_number });
  return r.data.channels;
}

export async function sendForgotPassword(personal_number: string, channel: string): Promise<void> {
  await api.post("/auth/forgot-password/send", { personal_number, channel });
}

export async function resetPassword(token: string, new_password: string): Promise<void> {
  await api.post("/auth/reset-password", { token, new_password });
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend
pnpm exec tsc --noEmit 2>&1 | head -20
```

Expected: no errors (or pre-existing errors only).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/auth.ts
git commit -m "feat: add email to Me type, add forgot/reset password API functions"
```

---

## Task 7: Forgot password and reset password pages + routes + i18n

**Files:**
- Create: `frontend/src/pages/ForgotPasswordPage.tsx`
- Create: `frontend/src/pages/ResetPasswordPage.tsx`
- Modify: `frontend/src/pages/LoginPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add i18n keys**

In `frontend/src/i18n/he.json`, add before the closing `}`:

```json
  "forgot_password": {
    "title": "שכחתי סיסמה",
    "personal_number_label": "מספר אישי",
    "continue": "המשך",
    "send_telegram": "📱 שלח לטלגרם",
    "send_email": "📧 שלח לאימייל",
    "no_channels": "לא נמצאו אמצעי קשר — פנה למנהל",
    "sent": "נשלח קישור לאיפוס סיסמה",
    "link_label": "שכחתי סיסמה",
    "back_to_login": "חזרה להתחברות"
  },
  "reset_password": {
    "title": "איפוס סיסמה",
    "new_password": "סיסמה חדשה",
    "confirm": "אימות סיסמה",
    "submit": "עדכן סיסמה",
    "submitting": "מעדכן...",
    "success": "הסיסמה עודכנה. ניתן להתחבר.",
    "errors": {
      "token_invalid": "קישור לא תקין או כבר נוצל",
      "token_expired": "פג תוקף הקישור — בקש קישור חדש",
      "password_too_short": "הסיסמה חייבת להכיל לפחות 10 תווים",
      "passwords_mismatch": "הסיסמאות אינן תואמות"
    }
  }
```

- [ ] **Step 2: Create ForgotPasswordPage.tsx**

Create `frontend/src/pages/ForgotPasswordPage.tsx`:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { checkForgotPasswordChannels, sendForgotPassword } from "../api/auth";

type Step = "input" | "choose" | "sent";

export default function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>("input");
  const [personalNumber, setPersonalNumber] = useState("");
  const [channels, setChannels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCheck() {
    setLoading(true);
    setError(null);
    try {
      const ch = await checkForgotPasswordChannels(personalNumber);
      setChannels(ch);
      setStep("choose");
    } catch {
      setError(t("login.errors.network"));
    } finally {
      setLoading(false);
    }
  }

  async function handleSend(channel: string) {
    setLoading(true);
    setError(null);
    try {
      await sendForgotPassword(personalNumber, channel);
      setStep("sent");
    } catch {
      setError(t("login.errors.network"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6" dir="rtl">
      <div className="w-full max-w-sm bg-white shadow rounded-lg p-6 space-y-4">
        <h1 className="text-2xl font-bold text-center">{t("forgot_password.title")}</h1>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        {step === "input" && (
          <div className="space-y-3">
            <label className="block text-sm">
              {t("forgot_password.personal_number_label")}
              <input
                type="text"
                inputMode="numeric"
                className="mt-1 block w-full border rounded p-2"
                value={personalNumber}
                onChange={e => setPersonalNumber(e.target.value)}
              />
            </label>
            <button
              onClick={handleCheck}
              disabled={loading || !personalNumber}
              className="w-full bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
            >
              {loading ? "..." : t("forgot_password.continue")}
            </button>
          </div>
        )}

        {step === "choose" && (
          <div className="space-y-3">
            {channels.length === 0 ? (
              <p className="text-sm text-gray-600">{t("forgot_password.no_channels")}</p>
            ) : (
              channels.map(ch => (
                <button
                  key={ch}
                  onClick={() => handleSend(ch)}
                  disabled={loading}
                  className="w-full border border-indigo-600 text-indigo-600 py-2 rounded hover:bg-indigo-50 disabled:opacity-50"
                >
                  {ch === "telegram" ? t("forgot_password.send_telegram") : t("forgot_password.send_email")}
                </button>
              ))
            )}
          </div>
        )}

        {step === "sent" && (
          <p className="text-green-700 text-sm text-center">{t("forgot_password.sent")}</p>
        )}

        <p className="text-center text-sm text-gray-500">
          <Link to="/login" className="text-indigo-600 hover:underline">
            {t("forgot_password.back_to_login")}
          </Link>
        </p>
      </div>
    </main>
  );
}
```

- [ ] **Step 3: Create ResetPasswordPage.tsx**

Create `frontend/src/pages/ResetPasswordPage.tsx`:

```tsx
import { useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { isAxiosError } from "axios";
import { resetPassword } from "../api/auth";

export default function ResetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mismatch = confirm.length > 0 && password !== confirm;

  async function handleSubmit() {
    if (password !== confirm) {
      setError(t("reset_password.errors.passwords_mismatch"));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await resetPassword(token, password);
      navigate("/login", { state: { resetSuccess: true }, replace: true });
    } catch (err) {
      const detail = isAxiosError(err) ? (err.response?.data?.detail as string | undefined) : undefined;
      const known: Record<string, string> = {
        token_invalid: t("reset_password.errors.token_invalid"),
        token_expired: t("reset_password.errors.token_expired"),
        password_too_short: t("reset_password.errors.password_too_short"),
      };
      setError(detail ? (known[detail] ?? detail) : t("login.errors.network"));
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <main className="min-h-screen flex items-center justify-center p-6" dir="rtl">
        <div className="text-center space-y-3">
          <p className="text-red-600">{t("reset_password.errors.token_invalid")}</p>
          <Link to="/forgot-password" className="text-indigo-600 hover:underline text-sm">
            {t("forgot_password.title")}
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6" dir="rtl">
      <div className="w-full max-w-sm bg-white shadow rounded-lg p-6 space-y-4">
        <h1 className="text-2xl font-bold text-center">{t("reset_password.title")}</h1>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        <label className="block text-sm">
          {t("reset_password.new_password")}
          <input
            type="password"
            className="mt-1 block w-full border rounded p-2"
            value={password}
            onChange={e => setPassword(e.target.value)}
          />
        </label>

        <label className="block text-sm">
          {t("reset_password.confirm")}
          <input
            type="password"
            className="mt-1 block w-full border rounded p-2"
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
          />
        </label>

        {mismatch && (
          <p className="text-red-500 text-xs">{t("reset_password.errors.passwords_mismatch")}</p>
        )}

        <button
          onClick={handleSubmit}
          disabled={submitting || !password || mismatch}
          className="w-full bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
        >
          {submitting ? t("reset_password.submitting") : t("reset_password.submit")}
        </button>

        <p className="text-center text-sm text-gray-500">
          <Link to="/forgot-password" className="text-indigo-600 hover:underline">
            {t("forgot_password.title")}
          </Link>
        </p>
      </div>
    </main>
  );
}
```

- [ ] **Step 4: Add "שכחתי סיסמה" link to LoginPage**

In `frontend/src/pages/LoginPage.tsx`, add after the register link `<p>`:

```tsx
<p className="text-center text-sm text-gray-500">
  <a href="/forgot-password" className="text-indigo-600 hover:underline">
    {t("forgot_password.link_label")}
  </a>
</p>
```

- [ ] **Step 5: Add success banner to LoginPage**

In `LoginPage.tsx`, add at the top of the component:

```tsx
import { useLocation } from "react-router-dom";
```

And at the top of the component body:

```tsx
const location = useLocation();
const resetSuccess = (location.state as { resetSuccess?: boolean } | null)?.resetSuccess;
```

And in the JSX, just inside the `<form>`, before the `<h1>`:

```tsx
{resetSuccess && (
  <div className="text-green-700 text-sm bg-green-50 rounded p-2 text-center">
    {t("reset_password.success")}
  </div>
)}
```

- [ ] **Step 6: Register new routes in App.tsx**

In `frontend/src/App.tsx`, add imports:

```tsx
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
```

Add routes alongside `/register` (public, no auth required):

```tsx
<Route path="/forgot-password" element={<ForgotPasswordPage />} />
<Route path="/reset-password" element={<ResetPasswordPage />} />
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd frontend
pnpm exec tsc --noEmit 2>&1 | head -20
```

Expected: no new errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/ForgotPasswordPage.tsx frontend/src/pages/ResetPasswordPage.tsx \
        frontend/src/pages/LoginPage.tsx frontend/src/App.tsx frontend/src/i18n/he.json
git commit -m "feat: forgot password and reset password pages, login link, i18n"
```

---

## Task 8: Email field in Profile, Registration, and SoldierEditModal

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx`
- Modify: `frontend/src/pages/RegisterPage.tsx`
- Modify: `frontend/src/components/SoldierEditModal.tsx`

- [ ] **Step 1: Add email field to ProfilePage**

In `ProfilePage.tsx`, find where `genderReq` state is declared and add:

```tsx
const [emailReq, setEmailReq] = useState(user?.email ?? "");
```

In the JSX where the profile update fields are shown (near gender/mitvahim fields), add:

```tsx
<div className="space-y-1">
  <label className="block text-sm font-medium">{t("profile.email")}</label>
  <div className="flex gap-2">
    <input
      type="email"
      className="border rounded p-1 text-sm flex-1"
      value={emailReq}
      onChange={e => setEmailReq(e.target.value)}
      placeholder="כתובת אימייל"
    />
    <button
      className="text-xs bg-indigo-600 text-white px-2 py-1 rounded"
      onClick={() => submitFieldUpdate({ field_name: "email", new_value: emailReq })}
    >
      {t("approvals.approve")}
    </button>
  </div>
</div>
```

Note: email is a direct update (not through field_update approval workflow — it's personal contact info the soldier controls). Use the `/me/profile` or a direct update. Since `email` isn't a sensitive field requiring approval, update it directly via `PUT /soldiers/{id}/profile`. Check how `phone` is updated in `ProfilePage` for the exact pattern to follow.

Actually, looking at the current ProfilePage — it submits field updates for mitvahim/alal/gender. Email should be a direct update since it's the soldier's own contact info. Add email to the `UpdateProfileRequest` in soldiers.py and call it directly. Alternatively, since `me.py` doesn't have a profile update endpoint, use `PATCH /soldiers/{user.id}/profile`.

- [ ] **Step 2: Add email to UpdateProfileRequest in soldiers.py**

In `backend/app/routes/soldiers.py`, add to `UpdateProfileRequest`:

```python
email: str | None = None
```

And in the `update_profile` route, the `fields` dict will automatically include it if provided (since `update_soldier_profile` handles arbitrary field updates). Verify `update_soldier_profile` in `app/services/soldiers.py` accepts `email`.

Check `backend/app/services/soldiers.py` — find `update_soldier_profile` and add `email` to the list of allowed fields if it has an allowlist, or confirm it uses `setattr` generically.

- [ ] **Step 3: Add email field to RegisterPage step 2**

In `frontend/src/pages/RegisterPage.tsx`, add `email: string` to the `FormData` interface:

```typescript
interface FormData {
  // existing fields...
  email: string;
}
```

Add `email: ""` to `INITIAL`. In the `handleSubmit` payload, add `email: form.email || null`.

In the `RegisterPayload` in `api/auth.ts`, add `email: string | null`.

In `RegisterPage` step 2, add after the phone input in the mapped field list:

```typescript
["email", "אימייל", "email"] as [keyof FormData, string, string]
```

- [ ] **Step 4: Add email field to SoldierEditModal (admin only)**

`SoldierEditModal` receives a `soldier: SoldierDTO`. First add `email?: string | null` to `SoldierDTO` in `frontend/src/api/soldiers.ts`.

In `SoldierEditModal.tsx`, add `email` state and conditionally render it based on the viewer's role. Since `SoldierEditModal` doesn't receive the current user, pass `isAdmin: boolean` as a prop, or check from `useAuth()`:

```tsx
import { useAuth } from "../auth/AuthContext";
// ...
const { user: currentUser } = useAuth();
const [email, setEmail] = useState(soldier.email ?? "");
```

Add `email?: string | null` to the `onSave` data type and pass it when admin.

In the form JSX, add (visible only to admin):

```tsx
{currentUser?.role === "admin" && (
  <label className="block">
    <span className="text-xs">אימייל</span>
    <input
      type="email"
      className="border rounded p-1 w-full"
      value={email}
      onChange={(e) => setEmail(e.target.value)}
    />
  </label>
)}
```

Include `email: email || null` in the `data` object when admin.

- [ ] **Step 5: Add `profile.email` i18n key**

In `frontend/src/i18n/he.json`, add to the `"profile"` section:

```json
"email": "כתובת אימייל"
```

- [ ] **Step 6: Run full test suite**

```bash
cd backend
uv run pytest tests/ -q 2>&1 | tail -15
```

Expected: all tests pass (existing failures unchanged).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/ProfilePage.tsx frontend/src/pages/RegisterPage.tsx \
        frontend/src/components/SoldierEditModal.tsx frontend/src/api/soldiers.ts \
        frontend/src/api/auth.ts frontend/src/i18n/he.json \
        backend/app/routes/soldiers.py
git commit -m "feat: email field in profile, registration, and admin soldier edit"
```

---

## Self-Review

### Spec coverage

| Spec section | Covered by |
|---|---|
| Migration: email on soldiers, password_reset_tokens table | Task 1 |
| SMTP settings (5 fields, all empty default) | Task 2 |
| `send_email()` no-ops when unconfigured | Task 2 |
| `available_channels()` — no enumeration on missing PN | Task 3 |
| Token invalidation on new request | Task 3 (`_create_reset_token` marks existing tokens used) |
| `POST /auth/forgot-password` — returns channels | Task 4 |
| `POST /auth/forgot-password/send` — always returns `{}` | Task 4 |
| `POST /auth/reset-password` — validates, updates, 400 on error | Task 4 |
| Rate limiting on forgot-password endpoints | Task 4 (uses `@limiter.limit`) |
| Rename `_can_see_gender` → `_can_see_private_fields` | Task 5 |
| email in `SoldierOut` gated by `_can_see_private_fields` | Task 5 |
| email in `MeResponse` | Task 5 |
| `checkForgotPasswordChannels`, `sendForgotPassword`, `resetPassword` | Task 6 |
| `Me` type gets `email` field | Task 6 |
| ForgotPasswordPage (two-step) | Task 7 |
| ResetPasswordPage | Task 7 |
| Login page: "שכחתי סיסמה" link | Task 7 |
| Login page: success banner after reset | Task 7 |
| Routes: `/forgot-password`, `/reset-password` | Task 7 |
| i18n keys | Task 7 |
| Email field in ProfilePage | Task 8 |
| Email field in RegisterPage step 2 | Task 8 |
| Email field in SoldierEditModal (admin only) | Task 8 |

### Type consistency check
- `PasswordResetToken` model field names match between migration and model class ✓
- `create_and_send` called in route with `personal_number=` and `channel=` — matches service signature ✓
- `redeem_reset_token` returns string literals `"ok"`, `"token_invalid"`, `"token_expired"`, `"password_too_short"` — route checks for `"ok"` and raises on others ✓
- `checkForgotPasswordChannels` returns `string[]` — ForgotPasswordPage uses `channels.map(ch => ...)` ✓
- `resetPassword(token, new_password)` — called in ResetPasswordPage as `resetPassword(token, password)` ✓
