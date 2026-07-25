# Announcements — design spec

## Goal

Let commanders and duty managers announce things to the soldiers they're
responsible for, and let admins broadcast org-wide. Recipients see it in the
app as a notification, visually distinguishable (different icon) between a
scoped/personal announcement and a true system-wide one. Senders can see a
history of what they've sent, including read receipts (who has and hasn't
read it).

## Current state

Most of the backend plumbing for this already exists but is completely
unreachable from the UI:

- `NotificationType.announcement` already exists
  (`backend/app/db/models.py:927`).
- `broadcast_announcement()` (`backend/app/services/notifications.py:711`)
  already resolves a soldier list from `hierarchy_node_ids` (or everyone if
  omitted) and calls `create_notification()` per recipient.
- `POST /notifications/announce` (`backend/app/routes/notifications.py:267`)
  already enforces: admins may omit `hierarchy_node_ids` (org-wide); anyone
  else must supply node ids that are within their own scope
  (`scope_root_ids()` / `_node_in_scope()` from `backend/app/auth/authz.py`).
- `NotificationBell.tsx` / `NotificationsPage.tsx` already render a
  `typeLabels` emoji map keyed by `NotificationType`, with `announcement: "📢"`
  already present in both.
- **Nothing in the frontend calls `/notifications/announce`.** There is no
  compose form, no API wrapper, no nav entry — the endpoint is dead code.
- `Notification` (`backend/app/db/models.py:945`) has `is_read: bool` but no
  timestamp of when it was read, and no table groups the N per-recipient rows
  created by one broadcast back into a single "sent announcement" — so there
  is currently no way to list "announcements I've sent" or see who read one.
- Hierarchy scoping precedent: `scope_root_ids(session, user)`
  (`backend/app/auth/authz.py:108`) returns the set of node ids a
  commander/DM oversees; `_node_in_scope()` checks subtree containment via
  `HierarchyNode.path_ids`. This is the existing idiom used by
  exemptions/swaps and already used by the announce route itself.
- `GET /hierarchy/tree` (`backend/app/routes/hierarchy.py:249`) returns the
  **entire** org tree regardless of role — not suitable as-is for a
  "pick a sub-unit within your own scope" picker.
- `HierarchyNodePickerModal.tsx` exists but fetches the full org tree with no
  scope filtering — not reused here (see rejected approaches below).

## Rejected approaches

- **Reusing `HierarchyNodePickerModal` as-is**: it lists the whole org tree.
  A commander could pick a node outside their scope and get a 403 on submit —
  confusing, and still needs a new scoped endpoint to fix properly, so it
  doesn't save backend work.
- **No node picker at all (whole-scope-only targeting)**: simplest UI, but a
  commander who oversees multiple sub-units (e.g. two companies) can't narrow
  an announcement to just one.
- **Icon chosen by sender role** (admin always gets the "system-wide" icon):
  rejected — an admin announcement scoped to one unit should look like any
  other scoped announcement, not a false "everyone" signal.

## Data model

**`Notification`** (`backend/app/db/models.py:945`) — add:
```python
read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
```
Set alongside `is_read = True` in both places it's currently set:
`mark_read()` and `mark_all_read()` (`backend/app/services/notifications.py:671,678`).

**`NotificationType`** (`backend/app/db/models.py`, enum) — add:
```python
system_announcement = "system_announcement"
```
(existing `announcement` value is kept, now meaning "scoped/personal")

**New table `Announcement`**:
| column | type | notes |
|---|---|---|
| `id` | UUID pk | `gen_random_uuid()` |
| `title` | Text | not null |
| `body` | Text | nullable |
| `type` | Enum(`NotificationType`) | `announcement` or `system_announcement` only |
| `sender_id` | UUID FK → soldiers.id | not null |
| `hierarchy_node_ids` | UUID[] | null/empty = org-wide |
| `recipient_count` | Integer | not null, snapshot at send time |
| `created_at` | timestamptz | server default `now()` |

One row per broadcast action. Each per-recipient `Notification` created by
that broadcast sets `reference_type="announcement"`, `reference_id=<Announcement.id>`
(the existing polymorphic reference columns already on `Notification`, no
schema change needed there beyond `read_at`).

## Backend

**`broadcast_announcement()`** (`backend/app/services/notifications.py:711`):
- Determine type: `hierarchy_node_ids` empty/None → `NotificationType.system_announcement`;
  otherwise → `NotificationType.announcement`. Scope-driven, not sender-driven.
- Insert one `Announcement` row first, capturing `recipient_count = len(soldiers)`.
- Pass `reference_type="announcement", reference_id=announcement.id` through
  to each `create_notification()` call.
- Return the created `Announcement` (route uses this to build the response).

**`POST /notifications/announce`** (`backend/app/routes/notifications.py:267`):
unchanged authz; response body extended to include the new announcement's
`id` and `recipient_count`.

**New `GET /notifications/announce/scope`**:
- For commander/DM callers: returns nodes in their own scope
  (`id, name, level`), derived from `scope_root_ids()` — i.e. the roots
  themselves plus (optionally) their descendants for narrowing. For a first
  version, return just the roots (the nodes the user directly commands or
  has a `DutyManagerScope` row for) — narrowing to a specific root is
  sufficient; deeper sub-selection is out of scope for v1.
- For admin callers: returns `[]` (they default to org-wide; if they want to
  narrow, the same picker component can be pointed at the existing
  `GET /hierarchy/tree` instead, chosen client-side by role — no backend
  change needed for that path).

**New `GET /notifications/announcements`** (history, paginated):
- Returns announcements where `sender_id == current_user.id`, newest first.
- Each row: `id, title, body, type, created_at, recipient_count, read_count`
  (`read_count` = `COUNT(Notification.id)` where `reference_id = Announcement.id
  AND is_read = true`).

**New `GET /notifications/announcements/{id}/recipients`**:
- 404/403 if the announcement doesn't belong to the caller.
- Returns every `Notification` row for that `reference_id`, joined to
  `Soldier` for `full_name`: `{soldier_id, full_name, is_read, read_at}`.

## Frontend

**New page `/announcements`** (nav entry visible to commanders, duty
managers, and admins — same visibility rule already used elsewhere for
`is_commander || is_duty_manager || role == "admin"`):

- **Compose form**: title (required), body (optional), target picker.
  - Commander/DM: fetches `GET /notifications/announce/scope`; defaults to
    "everyone under my command" (all returned roots pre-selected, zero
    clicks for the common case); checkboxes let them narrow to a subset of
    their own roots.
  - Admin: defaults to "everyone" (no node ids sent); an "narrow to a unit"
    toggle switches to the existing full-tree `HierarchyNodePickerModal` for
    manual multi-node selection if they want a targeted broadcast instead.
  - Submit → `POST /notifications/announce`.
- **History list** below the form: paginated, from
  `GET /notifications/announcements`. Each row: title, sent date, type icon,
  `read_count / recipient_count`, click-through to a **recipient detail
  view** listing every recipient with a read/unread badge and `read_at` if
  read (from `GET /notifications/announcements/{id}/recipients`).

**Icons**: `NotificationBell.tsx:76-83` and `NotificationsPage.tsx:41-47`
`typeLabels` maps both get `system_announcement: "📣"` added alongside the
existing `announcement: "📢"`.

**New `frontend/src/api/announcements.ts`**: thin wrappers for the four
endpoints above (`postAnnouncement`, `getAnnounceScope`, `listAnnouncements`,
`getAnnouncementRecipients`), mirroring the existing `api/notifications.ts`
style.

## Testing

Backend (pytest, mirroring existing patterns in `tests/integration/` and
`tests/unit/`):
- `broadcast_announcement` picks `system_announcement` when node ids are
  omitted, `announcement` when scoped — regardless of sender role.
- Non-admin caller without `hierarchy_node_ids` → 403
  (`org_wide_announcement_requires_admin`, already covered — verify still
  passes after the response-shape change).
- Non-admin caller with an out-of-scope node id → 403 (already covered,
  same verification).
- `GET /notifications/announce/scope` returns only the caller's own roots
  for a commander/DM, `[]` for admin.
- `GET /notifications/announcements` recipient/read counts match the
  underlying `Notification` rows.
- `mark_read`/`mark_all_read` set `read_at`.
- `GET /notifications/announcements/{id}/recipients` 403s for a non-owner.

Frontend (vitest):
- Compose form: default selection, submit calls the API with the right
  payload shape for commander vs admin.
- History list renders read/recipient counts.
- `typeLabels` maps render the correct icon for each of the two types.
