# Notifications System + Telegram Bot — Design

**Date:** 2026-06-01
**Status:** Approved for implementation

---

## 1. Purpose and scope

Add a notification system that delivers in-app notifications to soldiers and push
notifications via a Telegram bot. Soldiers link their Telegram account via a one-time
code flow and verify it through the bot. Commanders can opt into receiving
notifications about their subordinates' activities, scoped to specific hierarchy
nodes or individual soldiers. Every notification type can be independently enabled
or disabled for in-app and push delivery.

**In scope:**

- Database models: `notifications`, `telegram_links`, `notification_preferences`,
  `commander_notification_scopes`, `telegram_outbox`
- Notification creation from service layer events (swap, exemption, constraint,
  assignment, score, announcement)
- Cascade notifications to commanders based on their configured scopes
- API routes: notifications CRUD, preferences, commander scopes, telegram linking
- Telegram bot: standalone process with long-polling, verification flow, send
  messages from `telegram_outbox` queue
- Frontend: NotificationBell + dropdown, NotificationsPage, preferences page,
  commander scopes page, telegram link section in profile
- Backend notification service integrated inline (same pattern as audit writer)
- Migrations for all new tables

**Out of scope:**

- Email/SMS channels (Telegram is the only push channel)
- WebSocket or SSE (polling only for in-app)
- Automatic announcements (admin must trigger manually via API or seed script)
- Multi-language bot responses (Hebrew only, matching the app)

---

## 2. Data model

### 2.1 `notifications`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | `gen_random_uuid()` |
| `soldier_id` | `UUID FK → soldiers` | NOT NULL, indexed |
| `title` | `Text` | NOT NULL, short Hebrew title |
| `body` | `Text NULL` | Optional detail text |
| `type` | `Enum` | `swap_offer`, `swap_accepted`, `swap_rejected`, `exemption_approved`, `exemption_rejected`, `constraint_approved`, `constraint_rejected`, `assignment_created`, `assignment_removed`, `score_adjusted`, `announcement` |
| `reference_type` | `Text NULL` | e.g. `"swap_request"` |
| `reference_id` | `UUID NULL` | FK target, nullable for loose coupling |
| `is_read` | `Bool` | default `false`, indexed |
| `created_at` | `Timestamptz` | `server_default=now()` |

Index: `(soldier_id, is_read, created_at DESC)` for efficient unread-count queries.

### 2.2 `telegram_links`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `soldier_id` | `UUID FK → soldiers` | UNIQUE, one link per soldier |
| `telegram_chat_id` | `BigInt NULL` | Set on successful verification |
| `telegram_username` | `Text NULL` | Provided by bot after verification |
| `verification_code` | `Text NULL` | 6-character alphanumeric (e.g. `A3K9X2`) |
| `verification_expires_at` | `Timestamptz NULL` | 10 minutes from generation |
| `is_verified` | `Bool` | default `false` |
| `notifications_enabled` | `Bool` | default `true` |
| `created_at` | `Timestamptz` | |
| `verified_at` | `Timestamptz NULL` | |

### 2.3 `notification_preferences`

Per-soldier, per-type toggle for in-app and push delivery.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `soldier_id` | `UUID FK → soldiers` | |
| `notification_type` | `Enum` | Same values as `notifications.type` |
| `in_app_enabled` | `Bool` | default `true` |
| `push_enabled` | `Bool` | default `false` |
| `UNIQUE(soldier_id, notification_type)` | | One row per type per soldier |

On first access, missing rows are created with defaults (in_app=true, push=false)
for all known notification types.

### 2.4 `commander_notification_scopes`

Controls which subordinates a commander receives notifications about.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `commander_id` | `UUID FK → soldiers` | |
| `hierarchy_node_id` | `UUID FK → hierarchy_nodes` | The node whose subtree is included |

Multiple rows per commander. If the commander's scope nodes include `[A, B]`, any
notification for a soldier whose `hierarchy_node.path_ids` contains A or B triggers
a commander notification. When a commander adds "direct reports only", the UI adds
one scope row per immediate child node of their command nodes.

### 2.5 `telegram_outbox`

Queue table decoupling notification creation from bot delivery.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `telegram_chat_id` | `BigInt` | Target chat |
| `message_text` | `Text` | Ready-to-send message |
| `created_at` | `Timestamptz` | |
| `sent_at` | `Timestamptz NULL` | Set when bot confirms delivery |
| `error` | `Text NULL` | Set on permanent failure |

Index: `(sent_at NULLS FIRST, created_at)` — bot polls `WHERE sent_at IS NULL`.

---

## 3. Notification creation flow

### 3.1 Direct notifications (for the affected soldier)

When a service makes a state change that should notify someone:

```python
# Inside services/swaps.py
from app.services.notifications import create_notification

def approve_swap(session, swap_id, actor_id):
    swap = session.get(SwapRequest, swap_id)
    # ... existing logic ...
    create_notification(
        session,
        soldier_id=swap.requester_id,
        type="swap_accepted",
        title="בקשת החלפה אושרה",
        body=f"בקשת ההחלפה שלך עם {swap.target.name} אושרה",
        reference_type="swap_request",
        reference_id=swap.id,
        actor_id=actor_id,
    )
```

`create_notification`:
1. Checks `notification_preferences` for `in_app_enabled` — if true, inserts row
2. If `push_enabled` true for this type + soldier has a verified telegram link,
   inserts into `telegram_outbox`
3. Calls `cascade_to_commanders(session, soldier_id, ...)` — queries
   `commander_notification_scopes` to find commanders whose scopes include the
   soldier's hierarchy node, creates notifications + outbox entries for them
4. Writes audit row

### 3.2 Which services call `create_notification`

| Service | Notification types |
|---|---|
| `swaps.py` | `swap_offer` (to target), `swap_accepted`, `swap_rejected` |
| `exemptions.py` | `exemption_approved`, `exemption_rejected` |
| `constraints.py` (approval) | `constraint_approved`, `constraint_rejected` |
| `assignments.py` | `assignment_created`, `assignment_removed` |
| `adjustments.py` | `score_adjusted` |
| New announcement endpoint | `announcement` (admin broadcast) |

### 3.3 Commander cascade

`cascade_to_commanders(session, soldier_id, title, body, type, reference_type,
reference_id, actor_id)`:

1. Load the soldier's `hierarchy_node_id`
2. Query `commander_notification_scopes` for rows where the soldier's node
   `path_ids @> ARRAY[scope.hierarchy_node_id]` (the soldier's path contains the
   scope node)
3. For each matched commander, call `create_notification` recursively (which checks
   their own preferences)

### 3.4 Announcements

A dedicated admin endpoint `POST /api/notifications/announce` takes `{ title, body,
hierarchy_node_ids?: UUID[] }`. If `hierarchy_node_ids` is provided, notifies all
soldiers whose node is in those subtrees. If omitted, notifies all soldiers
(broadcast). Iterates and creates a notification for each recipient.

---

## 4. Telegram bot

### 4.1 Architecture

Standalone Python process using `python-telegram-bot` v20+ (`Application` class).
Connects to the same PostgreSQL database via a dedicated session. Polls Telegram
API (`getUpdates`) — no public URL required.

### 4.2 Commands

| Command | Flow |
|---|---|
| `/start` | Sends welcome message in Hebrew: "ברוכים הבאים! כדי לקשר את חשבון הטלגרם שלך, פתח קישור באתר והזן את הקוד שקיבלת." |
| `/verify <CODE>` | Looks up `telegram_links` by `verification_code` where `verification_expires_at > now()` and `is_verified=false`. If found: sets `telegram_chat_id`, `telegram_username`, `is_verified=true`, `verified_at=now()`. Clears `verification_code`. Replies "החשבון שלך אומת בהצלחה!" or "קוד לא תקין או שפג תוקפו." |
| `/status` | Checks if `telegram_chat_id` matches the sender. Replies linked/unlinked status in Hebrew. |
| `/unlink` | Sets `telegram_chat_id=NULL`, `is_verified=false`. Replies "החשבון בוטל בהצלחה." |
| `/help` | Lists available commands in Hebrew. |

### 4.3 Outbox processing loop

Every 2 seconds, the bot queries:
```sql
SELECT * FROM telegram_outbox
WHERE sent_at IS NULL
ORDER BY created_at
LIMIT 20
```

For each row: sends the message via `bot.send_message(chat_id=row.telegram_chat_id,
text=row.message_text)`. On success → sets `sent_at`. On permanent failure (chat
blocked, user stopped bot) → sets `error` and does not retry. On transient failure
→ leaves `sent_at` NULL for retry.

### 4.4 Bot token

Loaded from `TELEGRAM_BOT_TOKEN` environment variable (added to `.env.example` and
`settings.py`). The bot process also reads `DATABASE_URL` for DB access.

---

## 5. API routes

### 5.1 `/api/notifications`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/notifications` | Any user | List own notifications (paginated, newest first, optional `is_read` filter, optional `type` filter) |
| `GET` | `/api/notifications/unread-count` | Any user | `{ count: int }` for badge |
| `PATCH` | `/api/notifications/{id}/read` | Any user | Mark single as read |
| `PATCH` | `/api/notifications/read-all` | Any user | Mark all as read (`{ affected: int }`) |
| `DELETE` | `/api/notifications/{id}` | Any user | Dismiss (delete) a notification |

### 5.2 `/api/notifications/preferences`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/notifications/preferences` | Any user | Get preferences (auto-create missing rows) |
| `PUT` | `/api/notifications/preferences` | Any user | Bulk update: `{ preferences: [{ notification_type, in_app_enabled, push_enabled }] }` |

### 5.3 `/api/notifications/commander-scopes`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/notifications/commander-scopes` | Commander/DM/Admin | List scopes with hierarchy node names |
| `POST` | `/api/notifications/commander-scopes` | Commander/DM/Admin | Add scope: `{ hierarchy_node_id: UUID }` |
| `DELETE` | `/api/notifications/commander-scopes/{id}` | Commander/DM/Admin | Remove scope |

### 5.4 `/api/notifications/announce`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/notifications/announce` | Admin | `{ title, body?, hierarchy_node_ids?: UUID[] }` — if omitted, broadcasts to all |

### 5.5 `/api/telegram/link`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/telegram/link` | Any user | Generate verification code (6 chars, 10 min expiry), upsert into `telegram_links`. Returns `{ code, expires_at }` |
| `GET` | `/api/telegram/link/status` | Any user | `{ is_verified, telegram_username?, created_at, verified_at? }` — poll this after generating code |
| `DELETE` | `/api/telegram/link` | Any user | Unlink: clear chat_id, set is_verified=false |

---

## 6. Frontend

### 6.1 New files

- `src/api/notifications.ts` — all notification API calls
- `src/api/telegram.ts` — telegram link API calls
- `src/components/NotificationBell.tsx` — bell icon + badge + dropdown
- `src/pages/NotificationsPage.tsx` — full notification list with filters
- `src/components/NotificationPreferencesForm.tsx` — preference toggles
- `src/components/TelegramLinkSection.tsx` — link/unlink UI
- `src/components/CommanderNotificationScopes.tsx` — scope management
- `src/i18n/he.json` — extended with notification-related strings

### 6.2 Layout integration

The sidebar (Layout.tsx) gains a `NotificationBell` component at the top (before
nav links). It polls `GET /api/notifications/unread-count` every 30 seconds using
`setInterval` + `useQuery` with `refetchInterval: 30000`. The badge shows the count
(or hides at 0).

### 6.3 NotificationBell + Dropdown

- Bell icon (SVG from existing Heroicons or similar)
- Red badge circle with count (max 99+)
- On click: opens a small popover with:
  - "התראות" header + "סמן הכל כנקרא" link
  - List of last 5 unread notifications (each: icon by type, title, relative time,
    "✓" mark-read button, "✕" dismiss button)
  - "לכל ההתראות" link → navigates to `/notifications`
- Closes on click-outside

### 6.4 NotificationsPage (`/notifications`)

- Full-width table/list
- Filter bar: "הכל", "לא נקרא", filter by type (dropdown of all types)
- Each row: timestamp, type icon, title, body (truncated), reference link if
  applicable (clickable to navigate to the relevant page), mark-read/dismiss buttons
- Pagination (20 per page)
- "סמן הכל כנקרא" button at top

### 6.5 Notification preferences

Accessible from ProfilePage (`/profile`) as a section or tab:
- A table: one row per notification type, two toggle switches per row
  - "באפליקציה" (in-app toggle)
  - "בטלגרם" (push toggle)
- "שמור" button at bottom

### 6.6 Commander notification scopes

Accessible from ProfilePage for users with commander/DM/Admin roles:
- Current scopes shown as a list of hierarchy node names
- "הוסף תחום" button → opens hierarchy tree picker (reuse existing tree component)
- "הסר" button per scope row
- Helper text explaining the scope

### 6.7 Telegram link section

In ProfilePage, between general info and preferences:
- **Unlinked state:** "קשר חשבון טלגרם" button → shows code with copy button →
  "שלח קוד זה לבוט: @YourBotName" → auto-polls `/status` every 3s → shows success
- **Linked state:** "✅ מחובר ל-@username" with "נתק" (unlink) button

### 6.8 New route

```tsx
<Route path="/notifications" element={
  <ProtectedRoute><NotificationsPage /></ProtectedRoute>
} />
```

---

## 7. Migration

**Migration 0026** (single migration):

1. `CREATE TYPE notification_type AS ENUM (...)` — all 11 values
2. `CREATE TABLE notifications (...)`
3. `CREATE TABLE telegram_links (...)`
4. `CREATE TABLE notification_preferences (...)`
5. `CREATE TABLE commander_notification_scopes (...)`
6. `CREATE TABLE telegram_outbox (...)`
7. Indexes as described in §2

Reversible: `DROP TABLE` all 5 tables + `DROP TYPE notification_type`.

---

## 8. Configuration

New environment variables in `settings.py`:

| Variable | Type | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `str` | `""` | Bot token from @BotFather. Empty = bot disabled. |
| `TELEGRAM_BOT_USERNAME` | `str` | `""` | Bot username shown to users during linking |
