# Forgot Password Flow — Design Spec

**Date:** 2026-06-03  
**Status:** Approved

## Overview

Self-service password reset via a one-time link delivered to a soldier's verified Telegram account or registered email address. Soldiers with both channels choose which to use. Email infrastructure is added but left unconfigured; SMTP credentials are wired into settings for future activation.

---

## 1. Data Model

### 1a. `soldiers` table — new column

`email TEXT NULL` — soldier's email address. Private field: same visibility rules as `gender` (self, commanders in chain, duty managers, admins). Editable by the soldier via their own profile, and by admins via `SoldierEditModal`.

### 1b. New table: `password_reset_tokens`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `soldier_id` | UUID FK → soldiers CASCADE | |
| `token` | TEXT UNIQUE NOT NULL | 32-char random hex |
| `channel` | TEXT NOT NULL | `"telegram"` or `"email"` |
| `expires_at` | TIMESTAMPTZ NOT NULL | 15 minutes from creation |
| `used_at` | TIMESTAMPTZ NULL | Set on use; blocks replay |
| `created_at` | TIMESTAMPTZ NOT NULL | |

When a new token is created for a soldier, any existing unused tokens for that soldier are invalidated first (used_at set to now).

### 1c. Migration: `0033_forgot_password`

- `ALTER TABLE soldiers ADD COLUMN email TEXT NULL`
- `CREATE TABLE password_reset_tokens (...)`
- Index on `token` (unique), index on `soldier_id`

---

## 2. Email Infrastructure

### 2a. New SMTP settings (all optional, empty by default)

```
smtp_host: str = ""          # alias: SMTP_HOST
smtp_port: int = 587         # alias: SMTP_PORT
smtp_user: str = ""          # alias: SMTP_USER
smtp_password: str = ""      # alias: SMTP_PASSWORD
smtp_from: str = ""          # alias: SMTP_FROM
```

### 2b. `app/services/email.py` (new)

```python
def send_email(*, to: str, subject: str, body: str) -> bool
```

- Returns `False` silently if `smtp_host` is empty (not configured)
- Uses `smtplib.SMTP` with STARTTLS on the configured port
- Returns `True` on success, `False` + logs warning on failure
- No exceptions propagate to callers

---

## 3. Backend API

All new endpoints live in `app/routes/auth.py`.

### `POST /auth/forgot-password`

**Body:** `{ personal_number: str }`

**Behavior:**
- Looks up soldier by personal number
- Returns `{ channels: ["telegram", "email"] }` listing available delivery channels:
  - `"telegram"` if soldier has a verified TelegramLink
  - `"email"` if soldier has a non-null email
- If soldier not found: returns `{ channels: [] }` — no error to avoid personal number enumeration
- Rate-limited (same as login)

### `POST /auth/forgot-password/send`

**Body:** `{ personal_number: str, channel: "telegram" | "email" }`

**Behavior:**
- Looks up soldier; silently returns `{}` if not found
- Validates requested channel is available
- Invalidates existing unused tokens for this soldier
- Creates new `password_reset_tokens` row (expires in 15 min)
- Sends `{FRONTEND_URL}/reset-password?token=xxx` via the chosen channel:
  - **Telegram:** queues a `TelegramOutbox` message (no inline keyboard, plain text)
  - **Email:** calls `send_email(to=soldier.email, subject="איפוס סיסמה", body=...)`
- Always returns `200 {}` regardless of outcome

### `POST /auth/reset-password`

**Body:** `{ token: str, new_password: str }`

**Behavior:**
- Validates token: exists, `used_at IS NULL`, `expires_at > now()`
- Validates password policy (≥ 10 characters)
- Updates `soldier.password_hash`, sets `soldier.must_change_password = False`
- Sets `token.used_at = now()`
- Returns `200 {}`
- Errors: `token_invalid`, `token_expired`, `password_too_short`

---

## 4. Soldier Model Changes

### `GET /me` response
Add `email: str | null` field.

### `PUT /me/profile`
Add `email: str | null` to the update payload (soldier edits their own email).

### `GET /soldiers/:id`
Email included only when the requesting user passes the existing `_can_see_gender` check (self, commanders in chain, DMs, admins). Reuse the same boolean result: `include_email=include_gender`.

### `SoldierEditModal` (frontend)
Email field shown only when the current user is admin (same as gender field visibility in the admin UI).

---

## 5. Frontend

### Login page
Add "שכחתי סיסמה" link below the submit button → navigates to `/forgot-password`.

### `/forgot-password` page (new, public)

Two-step flow on one page:

**Step 1:** Text input for personal number + "המשך" button → calls `POST /auth/forgot-password`. Shows spinner while loading.

**Step 2 (inline, same page):** Renders available channel buttons:
- `📱 שלח לטלגרם` (if telegram in channels)
- `📧 שלח לאימייל` (if email in channels)
- `"לא נמצאו אמצעי קשר — פנה למנהל"` if channels is empty

Clicking a channel button → calls `POST /auth/forgot-password/send` → shows confirmation message: `"נשלח קישור לאיפוס סיסמה"`.

### `/reset-password` page (new, public)

- Reads `?token=` from URL query string
- Form: new password + confirm password
- On submit → calls `POST /auth/reset-password`
- On success: navigate to `/login` with a toast/banner: `"הסיסמה עודכנה. ניתן להתחבר."`
- On error: show translated Hebrew error, link back to `/forgot-password`

### Profile page
Add email field (editable, shows current value). Visible to the soldier themselves.

### Registration form step 2
Add optional email input field.

### `SoldierEditModal`
Add email field, visible only to admins.

---

## 6. i18n Keys (he.json)

```json
"forgot_password": {
  "title": "שכחתי סיסמה",
  "personal_number_label": "מספר אישי",
  "continue": "המשך",
  "send_telegram": "שלח לטלגרם",
  "send_email": "שלח לאימייל",
  "no_channels": "לא נמצאו אמצעי קשר — פנה למנהל",
  "sent": "נשלח קישור לאיפוס סיסמה",
  "link_label": "שכחתי סיסמה"
},
"reset_password": {
  "title": "איפוס סיסמה",
  "new_password": "סיסמה חדשה",
  "confirm": "אימות סיסמה",
  "submit": "עדכן סיסמה",
  "success": "הסיסמה עודכנה. ניתן להתחבר.",
  "errors": {
    "token_invalid": "קישור לא תקין או שפג תוקפו",
    "token_expired": "פג תוקף הקישור — בקש קישור חדש",
    "passwords_mismatch": "הסיסמאות אינן תואמות"
  }
}
```

---

## 7. Security Notes

- `POST /auth/forgot-password` never reveals whether a personal number exists
- `POST /auth/forgot-password/send` always returns `200 {}` regardless of outcome
- Tokens are 32 hex chars (16 random bytes = 128-bit entropy)
- Existing unused tokens for the same soldier are invalidated on new request
- `POST /auth/reset-password` error messages are generic (`token_invalid` covers both missing and used)
- Rate limiting on `/auth/forgot-password` prevents enumeration

---

## 8. Out of Scope

- SMS delivery
- Email templates (HTML email — plain text only for now)
- Admin-side "send reset link" action
- Token revocation UI
