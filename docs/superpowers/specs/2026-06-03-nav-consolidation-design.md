# Nav Consolidation & Planning Pages Design

**Date:** 2026-06-03  
**Status:** Approved

## Overview

Restructure the bottom nav / sidebar and the ManageSheet into a role-progressive layout. Collapse the five planning pages into two tabbed pages. Profile moves from a nav tab to a small header icon. No backend changes needed.

---

## Navigation Structure

### Header (all users)

| Position | Element | Visible to |
|----------|---------|-----------|
| Top-left | Profile icon (small, links to `/profile`) | All |
| Top-left | Gear icon (links to `/admin/settings`) | Admin only |
| Center | App title | All |
| Top-right | Notification bell | All |
| Top-right | Logout button | All |

Profile is **removed** from the bottom nav / sidebar entirely.

---

### Bottom Nav / Sidebar Tabs by Role

Tabs are always in this order; roles add tabs progressively:

| # | Label | Route | Roles |
|---|-------|-------|-------|
| 1 | הבקשות שלי | `/my-requests` | All |
| 2 | החלפות | `/swaps` | All |
| 3 | **בית** *(middle)* | `/` | All |
| 4 | לוח תורנויות | `/unit-calendar` | All |
| 5 | שקיפות | `/transparency` | All |
| 6 | מפקד | opens submenu | commander, duty_manager, admin |
| 7 | תכנון | opens submenu | duty_manager, admin |

Regular soldiers see tabs 1–5 only.  
Commanders see tabs 1–6.  
Duty managers and admins see tabs 1–7.

---

### מפקד Submenu (tab 6)

Opens a sheet/panel (same pattern as current ManageSheet):

| Label | Route |
|-------|-------|
| ניהול כח אדם | `/team` |
| אישור בקשות | `/approvals` |
| דשבורד מפקד | `/command-dashboard` |

---

### תכנון Submenu (tab 7)

| Label | Route |
|-------|-------|
| שיבוץ | `/planning/assignment` |
| הגדרת תורנויות ומשמרות | `/planning/config` |

---

### Admin Settings Page (`/admin/settings`)

Replaces the two separate admin pages. A single page with two tabs:

| Tab | Label | Content |
|-----|-------|---------|
| 0 | הגדרות מערכת | SystemSettingsPage content |
| 1 | קודי הזמנה | AdminInviteCodesPage content |

Accessible via gear icon in the header (admin only). The old routes `/admin/system-settings` and `/admin/invite-codes` redirect here.

---

## New Tabbed Planning Pages

### `/planning/assignment` — שיבוץ

| Tab | Label | Content |
|-----|-------|---------|
| 0 | שיבוץ ידני | DutyManagementPage content |
| 1 | אלגוריתם | AlgorithmPage content |

### `/planning/config` — הגדרת תורנויות ומשמרות

| Tab | Label | Content |
|-----|-------|---------|
| 0 | סוגי תורנויות | DutyConfigPage content |
| 1 | משמרות | ShiftsPage content |
| 2 | תבניות | ShiftTemplatesPage content |

Tab state stored in URL query param (`?tab=0`) so refresh/back works.

---

## Implementation Approach

### Step 1 — Extract content components

Five affected planning pages: extract their JSX body (excluding `<Layout>`) into a named export:

- `DutyManagementPage.tsx` → `DutyManagementContent`
- `AlgorithmPage.tsx` → `AlgorithmContent`
- `DutyConfigPage.tsx` → `DutyConfigContent`
- `ShiftsPage.tsx` → `ShiftsContent`
- `ShiftTemplatesPage.tsx` → `ShiftTemplatesContent`

Same for admin pages:
- `SystemSettingsPage.tsx` → `SystemSettingsContent`
- `AdminInviteCodesPage.tsx` → `AdminInviteCodesContent`

Each original page becomes: `<Layout><XContent /></Layout>` (preserves deep-link compatibility during transition).

### Step 2 — Create new tabbed pages

- `frontend/src/pages/planning/AssignmentPage.tsx` — tabs: שיבוץ ידני, אלגוריתם
- `frontend/src/pages/planning/ConfigPage.tsx` — tabs: סוגי תורנויות, משמרות, תבניות
- `frontend/src/pages/admin/AdminSettingsPage.tsx` — tabs: הגדרות מערכת, קודי הזמנה

### Step 3 — Update routing

New routes:
- `/planning/assignment` → `AssignmentPage`
- `/planning/config` → `ConfigPage`
- `/admin/settings` → `AdminSettingsPage`

Redirects from old routes:
- `/duty-management` → `/planning/assignment?tab=0`
- `/algorithm` → `/planning/assignment?tab=1`
- `/duty-config` → `/planning/config?tab=0`
- `/shifts` → `/planning/config?tab=1`
- `/shift-templates` → `/planning/config?tab=2`
- `/admin/system-settings` → `/admin/settings?tab=0`
- `/admin/invite-codes` → `/admin/settings?tab=1`

### Step 4 — Refactor UnifiedNav

Replace current role logic with the new progressive tab structure (tabs 1–5 for all, +tab 6 for commanders+, +tab 7 for duty_manager/admin). מפקד and תכנון tabs open submenus (same sheet pattern as current ManageSheet).

### Step 5 — Update Header (Layout.tsx)

- Add profile icon (top-left) linking to `/profile`
- Add gear icon (top-left, admin only) linking to `/admin/settings`
- Remove profile from nav tabs

### Step 6 — Remove ManageSheet

The current `ManageSheet` component is replaced by the two new submenu sheets (מפקד and תכנון). Delete `ManageSheet.tsx` after migration.

---

## Access Control Changes

| Page | Before | After |
|------|--------|-------|
| UnitCalendarPage | commander+ | **all users** |
| TransparencyPage | all users | all users (no change) |
| All other pages | unchanged | unchanged |

---

## Routes Removed (after migration)

Old standalone pages can be deleted once redirects are in place and verified:
`/duty-management`, `/algorithm`, `/duty-config`, `/shifts`, `/shift-templates`, `/admin/system-settings`, `/admin/invite-codes`

---

## Out of Scope

- Any changes to page content or functionality — purely structural
- Access control changes beyond UnitCalendar (noted above)
- MyDutiesPage — still exists, linked from the homepage dashboard widget
