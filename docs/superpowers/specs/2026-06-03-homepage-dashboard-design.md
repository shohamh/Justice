# Homepage Dashboard Design

**Date:** 2026-06-03  
**Status:** Approved

## Overview

Replace the placeholder `HomePage.tsx` with a real unified dashboard. All roles (soldier, commander, admin) see the same layout; role-specific sections appear or hide conditionally. Data is composed on the frontend by calling existing API endpoints in parallel.

## System Settings

Four new keys added to the existing settings system (visible/editable in the SystemSettingsPage under a new "דף הבית" group):

| Key | Default | Description |
|-----|---------|-------------|
| `home.mitvahim_validity_days` | 180 | How long a mitvahim is valid (days) |
| `home.mitvahim_warn_days` | 30 | Days before mitvahim expiry to start warning |
| `home.alal_validity_days` | 90 | How long an alal is valid (days) |
| `home.alal_warn_days` | 30 | Days before alal expiry to start warning |

These settings are read by the frontend via `GET /system-settings`.

## Data Sources

All fetched in parallel on mount via `Promise.all`:

| Data | Endpoint | Notes |
|------|----------|-------|
| Current user | auth context (`/me`) | Already available; provides `last_mitvahim_date`, `last_alal_date` |
| Upcoming duties | `GET /assignments/effective?soldier_id=…&date_from=today&date_to=today+60d` | Filter to next 5 |
| My swaps | `GET /swaps/my` | Filter to non-cancelled, non-applied |
| Pending approvals | `GET /enrollment-requests/pending` + `GET /swaps/pending` | Commander/admin only |
| Settings | `GET /system-settings` | For validity/warn thresholds |

## Widgets

### 1. Alert Banners (conditional, top of page)

Expiry logic: `expiry_date = last_X_date + validity_days`. Show banner if `expiry_date - today <= warn_days`.

- If `last_mitvahim_date` is null → yellow banner "תאריך מיתווחים לא מעודכן" 
- If mitvahim expiring within warn window → yellow banner "המיתווחים שלך פגים בתאריך X"
- If `last_alal_date` is null → yellow banner "תאריך אל\"ל לא מעודכן"
- If alal expiring within warn window → yellow banner "האל\"ל שלך פג בתאריך X"
- Each banner is dismissible (session-only, no persistence needed)
- Clicking a banner navigates to ProfilePage

### 2. Upcoming Duties

Card title: "תורנויות קרובות"

- Table: date range | duty type name | location name
- Shows next 5 effective assignments (sorted by start_date asc)
- "לכל התורנויות שלי →" link to MyDutiesPage
- Empty state: "אין תורנויות קרובות"

### 3. My Swaps

Card title: "החלפות שלי"

- List of active swap requests (status = open or pending_approval)
- Each row: duty date | status chip (color-coded) | reason
- "לדף החלפות →" link to SwapsPage
- Empty state: "אין החלפות פעילות"
- Hidden entirely if user has no swap requests at all

### 4. Pending Approvals (commanders and admins only)

Card title: "ממתינים לאישורך"

Shown only when `user.role === 'commander' || user.role === 'admin'`.

- Row 1: "בקשות הצטרפות ממתינות: N" — links to ApprovalsPage (or enrollment requests section)
- Row 2: "החלפות הממתינות לאישור: N" — links to SwapsPage
- Hidden if both counts are 0

## Frontend Implementation

- `HomePage.tsx` — orchestrates all data fetching, renders 4 widgets
- Extract each widget as a sub-component in `frontend/src/components/dashboard/`:
  - `AlertBanners.tsx`
  - `UpcomingDutiesWidget.tsx`
  - `SwapStatusWidget.tsx`
  - `PendingApprovalsWidget.tsx`
- Reuse existing API modules (`assignments`, `swaps`, `enrollment`, `systemSettings`)
- No new API modules needed

## Seed Enhancements

### More Swap Requests

Move swap seeding out of the `if with_assignments:` block. Swap requests reference existing `DutyAssignment` records, so they still require `with_assignments` data — but seed 10 total (up from 4):

| # | Status | Notes |
|---|--------|-------|
| 1 | open | no target |
| 2 | open | with target soldier |
| 3 | open | no target, different duty type |
| 4 | open | no target |
| 5 | pending_approval | covering soldier agreed |
| 6 | pending_approval | different shift |
| 7 | applied | completed |
| 8 | applied | different soldier |
| 9 | rejected | commander rejected |
| 10 | cancelled | requester cancelled |

### Enrollment Requests

Seed 4 `SoldierEnrollmentRequest` records directly in the `seed()` function (no `with_assignments` gate).

`SoldierEnrollmentRequest` is for soldiers who registered but have no node yet. Create 4 new soldiers with `hierarchy_node_id=None` (unassigned) and create enrollment requests for them:

| # | Status | requesting_node |
|---|--------|----------------|
| 1 | pending | team צוות מארס |
| 2 | pending | group מחקר |
| 3 | approved | team צוות ריי, `decided_by=s_admin.id` |
| 4 | rejected | team צוות ארק, `decided_by=s_admin.id` |

The 4 unassigned soldiers should be enlisted חובה with minimal fields (personal_number, name, password_hash, role="soldier").

### Invite Code

Seed 1 `RegistrationInviteCode` with `uses_left=10`, `created_by=s_admin.id`. This is not gated on any flag.

## Out of Scope

- Persisting banner dismissals across sessions
- Homepage customization / widget reordering
- Duty history graph or scoring summary on the homepage
