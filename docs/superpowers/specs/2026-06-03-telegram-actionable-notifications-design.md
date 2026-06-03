# Telegram Actionable Notifications — Design Spec

**Date:** 2026-06-03  
**Status:** Approved

## Overview

Make Telegram notifications interactive. Actionable notifications carry inline-keyboard buttons for approve/reject. Every notification carries a gender-aware "פתח/פתחי במערכת" deep-link. All buttons use one-time tokens stored in the DB to prevent replay attacks. A "silence" button lets soldiers/commanders adjust their push preferences without leaving Telegram; for commander-approval notification types, silence is a depth-based filter rather than a simple on/off.

---

## 1. New Notification Types

Three types are added (Alembic ALTER TYPE):

| Type | Sent when | Recipient | Actionable |
|---|---|---|---|
| `constraint_pending` | Soldier submits a constraint request | Commanders in scope | ✅ approve / reject |
| `exemption_request_pending` | Soldier submits an exemption request | Commanders in scope | ✅ approve / reject |
| `swap_offer_incoming` | Directed swap request created with `target_soldier_id` | Target soldier | ✅ approve (covering side) / reject |

Existing `swap_offer` (sent to the requesting soldier when a covering soldier claims) also gets approve/reject buttons.

---

## 2. Data Model

### 2a. `telegram_action_tokens` (new table)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `token` | TEXT UNIQUE NOT NULL | 16-char random hex; used as Telegram `callback_data` |
| `soldier_id` | UUID FK → soldiers | Owner; verified against their `telegram_chat_id` before execution |
| `action` | TEXT NOT NULL | e.g. `constraint:approve`, `swap:approve_covering`, `silence:depth` |
| `resource_type` | TEXT NULL | e.g. `constraint`, `swap_request`, `exemption_request` |
| `resource_id` | UUID NULL | The entity to act on |
| `extra_json` | JSONB NULL | Extra context, e.g. `{"notification_type":"constraint_pending"}` for silence |
| `expires_at` | TIMESTAMPTZ NOT NULL | 10 min for approve/reject; 30 min for silence |
| `used_at` | TIMESTAMPTZ NULL | Set on first use; blocks all replays |
| `awaiting_text_from_chat_id` | BIGINT NULL | Set when reject is tapped; cleared when text reply received |
| `created_at` | TIMESTAMPTZ NOT NULL | |

### 2b. `commander_notification_depth` (new table)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `commander_id` | UUID FK → soldiers | |
| `notification_type` | notification_type enum | Only meaningful for `constraint_pending` / `exemption_request_pending` |
| `max_depth` | INTEGER NULL | 1 = direct reports only; 2 = default; NULL = unlimited |
| UNIQUE | (commander_id, notification_type) | |

If no row exists for a commander + type, default `max_depth = 2` is applied in code.

### 2c. `telegram_outbox` — new column

`reply_markup_json TEXT NULL` — JSON-serialised Telegram `InlineKeyboardMarkup`; parsed and passed to `send_message` by the outbox poller.

---

## 3. Message Format & Inline Keyboards

### 3a. Actionable notifications

```
[✅ אשר]  [❌ דחה]
[🔕 השתק]
[🔗 פתח במערכת]   ← URL button (gender-aware label)
```

Types: `constraint_pending`, `exemption_request_pending`, `swap_offer`, `swap_offer_incoming`.

### 3b. Informational notifications

```
[🔕 השתק]
[🔗 פתח/פתחי במערכת]   ← URL button
```

### 3c. Gender-aware label

- `soldiers.gender = 'female'` → label is `פתחי במערכת`
- All other values → `פתח במערכת`

### 3d. Frontend URL mapping

New setting `FRONTEND_URL` (default `http://localhost:5173`). Path per type:

| Types | Path |
|---|---|
| `constraint_pending / approved / rejected` | `/constraints` |
| `exemption_request_pending / approved / rejected` | `/exemption-requests` |
| `swap_offer / swap_offer_incoming / accepted / rejected` | `/swaps` |
| `assignment_created / removed` | `/schedule` |
| `score_adjusted` | `/profile` |
| `announcement` | `/notifications` |
| `algorithm_job_done / failed` | `/algorithm` |

---

## 4. Reject → Reason Collection Flow

Reject actions require a `decision_note`. The bot handles this in two steps:

1. User taps **[❌ דחה]** → bot answers the callback and sends a new message: `"נא כתוב את סיבת הדחייה:"`. The token's `awaiting_text_from_chat_id` is set to the user's chat ID.
2. Next free-text message from that chat is intercepted by `handle_text_message` (replacing the current bare-code handler). The bot finds the pending token, executes the reject with the typed text as `decision_note`, marks the token used, and confirms.

Applies to: constraint reject, exemption request reject, swap reject.  
Approve actions proceed immediately (no reason required).

---

## 5. Cascade & Depth Filtering

### 5a. New sends

- `constraints.submit_constraint` → after creating the constraint, send `constraint_pending` to commanders in scope via `cascade_to_commanders`.
- `exemption_requests.submit_request` → send `exemption_request_pending` to commanders in scope.
- `swaps.create_request` (when `target_soldier_id` is set) → send `swap_offer_incoming` to the target soldier directly (not via cascade).

### 5b. Depth filtering in `cascade_to_commanders`

Depth filtering is applied only for `constraint_pending` and `exemption_request_pending`.

Algorithm per commander scope node:
1. Look up `commander_notification_depth` for (commander_id, notification_type). Use `max_depth = 2` if no row.
2. Find the scope node's index `k` in the soldier's `path_ids`.
3. Compute `depth = len(path_ids) - 1 - k` (how many levels below the scope node the soldier sits; 0 if soldier is a direct member of the scope node).
4. Skip this commander if `max_depth is not None and depth > max_depth`.

All other cascaded types are unaffected.

---

## 6. Silence Flow

### 6a. Regular soldiers (any notification type)

Single tap on **[🔕 השתק]** → sets `notification_preferences.push_enabled = false` for that type. Bot confirms: `"התראות [type] בטלגרם הושתקו."`

### 6b. Commanders — pending types (`constraint_pending`, `exemption_request_pending`)

Two-step flow:

1. Commander taps **[🔕 השתק]**.
2. Bot sends: `"עד כמה רמות מתחתיך תרצה לקבל התראות [type]?"` with buttons:
   ```
   [1 – ישיר בלבד]  [2]  [3]  [הכל]
   ```
3. Commander taps a number → upserts `commander_notification_depth` row; bot confirms.

"הכל" sets `max_depth = NULL` (unlimited). Tapping a number while an existing row exists updates it.

Commanders silencing other (non-pending) types follow the regular flow (push_enabled = false).

---

## 7. Token Security

- Token is 16 hex chars (8 random bytes); probability of collision negligible for short-lived tokens.
- `used_at` is set atomically on first use; subsequent callbacks with the same token return an error.
- Tokens are validated: not expired, not used, `soldier_id` matches the TelegramLink for the inbound `chat_id`.
- A background cleanup job (or inline check) purges tokens older than 24 hours.

---

## 8. Architecture — Bot calls service layer directly

Consistent with existing verification handler pattern. No internal HTTP.

### New / changed files

| File | Change |
|---|---|
| `app/settings.py` | Add `FRONTEND_URL` |
| `app/db/models.py` | Add `TelegramActionToken`, `CommanderNotificationDepth` models |
| `alembic/versions/0032_telegram_actions.py` | New migration |
| `app/services/action_tokens.py` *(new)* | `create_token`, `redeem_token`, `set_awaiting_reply`, `find_pending_reply` |
| `app/services/notifications.py` | `_enqueue_push` builds `reply_markup_json`; cascade applies depth filter |
| `app/services/constraints.py` | `submit_constraint` sends `constraint_pending` to commanders |
| `app/services/exemption_requests.py` | `submit_request` sends `exemption_request_pending` to commanders |
| `app/services/swaps.py` | `create_request` sends `swap_offer_incoming` to target |
| `bot/actions.py` *(new)* | Execute functions for each action type + silence logic |
| `bot/handlers.py` | Add `callback_query_handler`; extend text handler for pending-reply |
| `bot/outbox.py` | Parse `reply_markup_json`, pass to `send_message` |
| `bot/main.py` | Register `CallbackQueryHandler` |

---

## 9. Out of Scope

- Web UI for managing `commander_notification_depth` (depth is set via Telegram only for now)
- Push notifications via channels other than Telegram
- Rate limiting on action token creation
