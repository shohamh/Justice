# Feedback Batch (2026-07-22): 8 Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 8 independent product fixes requested by the product owner in one bundled feature branch off `dev`: (1) fix the one remaining American-format date display; (2) rename the driving-license-expiry field label; (3) stop the calendar's week/3-day view from forcing horizontal scroll on wide desktop screens; (4) fix duty cells rendering black instead of their duty-type color; (5) show a "constraint days remaining" indicator that resets quarterly/semi-annually/annually; (6) hide the Telegram notification-preference column when Telegram is globally disabled; (7) add two missing notification-type translations; (8) let every viewer see the full hierarchy tree (read-only outside their own scope), auto-expanded to and highlighting their own commanded node.

**Architecture:** Items 1, 2, 4, 6, 7 are small, single-file-ish fixes. Item 3 is a CSS/constants fix. Item 5 is a new vertical slice (service + route + frontend), following the existing `settings_loader`-backed system-setting pattern. Item 8 changes a backend route's filtering behavior and adds per-node permission/highlight logic to the existing hierarchy tree component.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React + TypeScript + react-i18next + TanStack Query (frontend), pytest (backend tests), vitest (frontend tests, where an area already has coverage).

## Global Constraints

- Hebrew UI text only (English code/identifiers) — every new user-facing string goes in `frontend/src/i18n/he.json`, dot-path keys following the existing per-page prefix convention (`notifications.*`, `hierarchy.*`, `constraints.*`, `admin_settings.*`).
- New system settings are stored via `app.services.settings_loader.get_setting`/`set_setting` against the existing `system_settings` JSONB table — do not create new settings tables.
- New Alembic migrations: `alembic revision -m "description"` from `backend/`, then hand-edit `upgrade()`/`downgrade()`. Do not use `--autogenerate` blindly — review the diff.
- Every backend service function takes `session: Session` first and returns/raises via a module-level `*Error` exception class where the file already follows that pattern — do not introduce a new error-handling style.
- Run targeted tests only per task (`pytest -m <area> -q` / `npm test -- <file>`); the full suite is not required until the branch is ready to merge.
- No commits directly to `master` or `dev` — this is one bundled feature branch per the user's explicit choice for this batch.

---

## Item 1 — Fix remaining American-format date

**Current bug:** `frontend/src/pages/planning/ScoreAdjustmentPage.tsx:338` renders `{a.created_at.slice(0, 10)}` directly (raw ISO `YYYY-MM-DD`) instead of using the app's canonical `formatDate` helper (`frontend/src/utils/formatDate.ts:7-16`, which renders `dd.mm.yyyy`). Every other date-display call site in the frontend already uses `formatDate`/`formatDdMmYyyy` or passes `"he-IL"` to `toLocaleDateString` — this is the one remaining offender.

### Task 1.1: Use `formatDate` in the score-adjustment history table

**Files:**
- Modify: `frontend/src/pages/planning/ScoreAdjustmentPage.tsx:338` (and its imports)

**Interfaces:**
- Consumes: `formatDate(d: string | Date): string` from `frontend/src/utils/formatDate.ts` (existing, unchanged).

- [ ] **Step 1:** Add the import near the top of `ScoreAdjustmentPage.tsx` (alongside existing imports):

```tsx
import { formatDate } from "../../utils/formatDate";
```

- [ ] **Step 2:** Replace the offending cell at line 338:

```tsx
// before
<td className="py-2 text-xs">{a.created_at.slice(0, 10)}</td>
// after
<td className="py-2 text-xs">{formatDate(a.created_at)}</td>
```

- [ ] **Step 3:** Manual check — start the dev stack, open the score-adjustment page (as admin/duty-manager), submit an adjustment, confirm the "recent adjustments" table shows the date as `dd.mm.yyyy` instead of `yyyy-mm-dd`.

- [ ] **Step 4: Commit** — `git add frontend/src/pages/planning/ScoreAdjustmentPage.tsx && git commit -m "fix: use Hebrew date format in score-adjustment history table"`

---

## Item 2 — Rename the license-expiry field label

**Current bug:** `frontend/src/i18n/he.json:509`, key `soldier_profile.military_driving_license_expiry`, currently reads `"תאריך תפוגה (תוקף רשנ\"צ, כפי שמופיע באפליקציית ארנק צה\"לי)"`. It backs both the value display (`frontend/src/pages/ProfilePage.tsx:252`) and is the only label associated with the expiry date input (`ProfilePage.tsx:342-349`). The product owner wants it changed to `"תאריך סיום תוקף רישיון צבאי"`.

### Task 2.1: Update the i18n string

**Files:**
- Modify: `frontend/src/i18n/he.json:509`

- [ ] **Step 1:** Change the value:

```json
"military_driving_license_expiry": "תאריך סיום תוקף רישיון צבאי",
```

- [ ] **Step 2:** Manual check — open the profile page, confirm the label next to the expiry date input, and the confirmed-license summary line, both read the new text.

- [ ] **Step 3: Commit** — `git add frontend/src/i18n/he.json && git commit -m "fix: rename military driving license expiry field label"`

---

## Item 3 — Calendar week/3-day view forces needless horizontal scroll on desktop

**Root cause:** `frontend/src/utils/calendarViewWidth.ts` hard-codes a 420px-per-day minimum column width, applied only to `timeGridWeek` (7 days → 3000px minimum) and `timeGridThreeDay` (3 days → 1320px minimum) via a CSS custom property consumed in `frontend/src/styles/globals.css:49-54`. 3000px exceeds even a 1920px-wide desktop viewport, forcing a scrollbar regardless of actual available width. Month view has no such minimum (`dayGridMonth` isn't in the day-count map) and correctly fills the container — that's the working reference behavior to match.

**Fix:** stop forcing an oversized minimum width on desktop; only apply a (smaller) per-day minimum on narrow viewports where the calendar genuinely needs horizontal scroll to stay legible (mobile). Use a CSS media query instead of always forcing the JS-computed minimum.

### Task 3.1: Cap the forced minimum width to narrow viewports only

**Files:**
- Modify: `frontend/src/utils/calendarViewWidth.ts:1-13`
- Modify: `frontend/src/styles/globals.css:49-54`

**Interfaces:**
- Produces: `calendarViewMinWidth(viewType: string): number | undefined` (unchanged signature) now returns a smaller per-day constant (140px, enough to keep one day's events legible on mobile) instead of 420px; the CSS only applies that minimum below a `768px` breakpoint, matching this codebase's existing mobile breakpoint convention (grep `md:` Tailwind usage elsewhere in the repo, which maps to 768px).

- [ ] **Step 1:** In `calendarViewWidth.ts`, reduce the per-day constant:

```ts
const DAY_COLUMN_MIN_PX = 140;
const TIME_AXIS_GUTTER_PX = 60;
export const CALENDAR_VIEW_DAY_COUNTS: Record<string, number> = {
  timeGridWeek: 7,
  timeGridThreeDay: 3,
};
export function calendarViewMinWidth(viewType: string): number | undefined {
  const dayCount = CALENDAR_VIEW_DAY_COUNTS[viewType];
  if (!dayCount) return undefined;
  return dayCount * DAY_COLUMN_MIN_PX + TIME_AXIS_GUTTER_PX;
}
```

(140px/day: week = 7×140+60 = 1040px, 3-day = 3×140+60 = 480px — both fit inside a typical ≥1280px desktop content area without scroll, while still giving mobile viewports a sane minimum to scroll to.)

- [ ] **Step 2:** In `globals.css`, gate the min-width rule behind a narrow-viewport media query so desktop always uses `auto` (fills container) regardless of the computed value:

```css
.fc-view-harness { overflow-x: auto; }
@media (max-width: 767px) {
  .fc-view-harness > .fc-view { min-width: var(--fc-grid-min-width, auto); }
}
```

(Desktop screens — ≥768px — no longer apply `min-width` at all, so week/3-day views fill the available container width exactly like month view already does; only mobile keeps the scrollable minimum.)

- [ ] **Step 3:** Manual check — start the dev stack, open the unit calendar at a desktop width (≥1280px), switch to week and 3-day views, confirm no horizontal scrollbar appears and columns fill the available width. Then resize to a narrow (< 768px) viewport and confirm the week/3-day views still scroll horizontally with readable column widths.

- [ ] **Step 4: Commit** — `git add frontend/src/utils/calendarViewWidth.ts frontend/src/styles/globals.css && git commit -m "fix: stop calendar week/3-day view from forcing scroll on desktop widths"`

---

## Item 4 — Some duty cells render black instead of their duty-type color

**Root cause:** `backend/app/services/calendar_shifts.py` builds a `duty_type_id -> (name, color)` map from all `DutyType` rows, then does `dt_map.get(shift.duty_type_id, ("", ""))` (lines ~250, ~325). When a shift references a `duty_type_id` that isn't in the map (e.g. an orphaned reference to a duty type that no longer exists), this silently returns an empty color string. That empty string flows straight into `backgroundColor`/`borderColor` in `frontend/src/components/UnitCalendar.tsx:95-96`, which isn't a valid CSS color, so the browser/FullCalendar falls back to default (black) styling.

**Fix:** never fall back to an empty color — if a shift's duty type is missing from the map, derive a deterministic color straight from the shift's own `duty_type_id` using the same hash formula already used elsewhere (`backend/app/routes/calendar.py:86-88`), so it's always a valid, stable color even for a dangling reference.

### Task 4.1: Fall back to a hash-derived color instead of an empty string

**Files:**
- Modify: `backend/app/services/calendar_shifts.py` (both `dt_map.get(...)` call sites, and the `dt_map` construction)
- Test: `backend/tests/services/test_calendar_shifts.py` (grep for existing shift-listing tests to find the right file/class — create if none exists for this module)

**Interfaces:**
- Produces: `calendar_shifts._duty_color_for(duty_type_id: uuid.UUID) -> str` returning `f"hsl({hash(duty_type_id) % 360}, 65%, 55%)"` (same formula as `routes/calendar.py:86-88`'s `_duty_type_color`, duplicated here rather than imported to avoid a routes→services import direction violation — check existing import direction conventions in `calendar_shifts.py` before deciding; if services already import from routes elsewhere in this codebase, import `_duty_type_color` directly instead of duplicating).

- [ ] **Step 1: Write the failing test:**

```python
def test_shift_with_missing_duty_type_gets_hash_color_not_black(session, soldier_factory, duty_type_factory):
    dt = duty_type_factory()
    soldier = soldier_factory()
    shift = create_shift_for(session, soldier_id=soldier.id, duty_type_id=dt.id)  # use existing shift-creation helper in this test module
    # simulate a dangling reference: delete the duty type row directly, leaving shift.duty_type_id orphaned
    session.execute(delete(DutyType).where(DutyType.id == dt.id))
    session.flush()

    rows = calendar_shifts.list_shifts_for_soldier(session, soldier_id=soldier.id)  # or whichever function returns dt_color-bearing rows — confirm exact function name via grep before writing this call
    row = next(r for r in rows if r["id"] == shift.id)
    assert row["duty_type_color"] != ""
    assert row["duty_type_color"].startswith("hsl(")
```

(Confirm the exact function name and return-dict shape by reading `calendar_shifts.py` around lines 82-95 and 250 before finalizing this test — the plan's snippets above describe the located code but the public function name wrapping it wasn't captured verbatim during research; grep `dt_map.get` to find the enclosing function.)

- [ ] **Step 2: Run test to verify it fails** — `pytest backend/tests/services/test_calendar_shifts.py -k missing_duty_type -v`.

- [ ] **Step 3: Implement.** Near the top of `calendar_shifts.py`, add the fallback helper:

```python
def _duty_color_for(duty_type_id: uuid.UUID) -> str:
    """Deterministic color from a duty_type_id alone — used when the id
    isn't present in the loaded DutyType map (e.g. a dangling reference),
    so a shift never falls back to an invalid empty color (which renders
    as black in the calendar UI)."""
    return f"hsl({hash(duty_type_id) % 360}, 65%, 55%)"
```

Replace both `dt_map.get(shift.duty_type_id, ("", ""))` call sites:

```python
dt_name, dt_color = dt_map.get(shift.duty_type_id, ("", _duty_color_for(shift.duty_type_id)))
```

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Commit** — `git add backend/app/services/calendar_shifts.py backend/tests && git commit -m "fix: never render a duty cell with an invalid empty color"`

---

## Item 5 — Constraint days remaining, resetting quarterly/semi-annually/annually

**Design:** confirmed via research that no part of this exists yet — `backend/app/services/constraints.py` has no `remaining_days`/`period_bounds`, no route exposes quota info to the current user, and `MyRequestsPage.tsx`'s constraint submission form shows no count at all. The only existing building block is the `constraints.personal_cap_days` system setting (default 15, read at `constraints.py:60`) and an internal `_future_cap_used()` helper that sums *all future* pending/approved constraint days — not period-scoped. This item adds a new `constraints.reset_period` setting (`"quarter"` | `"half_year"` | `"year"`, default `"quarter"`) and period-aware remaining-days computation, matching the on-the-fly (no background job, no anchor-date setting) style already used elsewhere in this codebase for period math.

### Task 5.1: Backend — compute remaining constraint days for the current period

**Files:**
- Modify: `backend/app/services/constraints.py` (add period helpers + `remaining_days`)
- Modify: `backend/app/routes/constraints.py` (add `GET /me/constraints/remaining`)
- Test: `backend/tests/services/test_constraints.py`

**Interfaces:**
- Produces: `constraints.period_bounds(reset_period: str, today: date) -> tuple[date, date]` (inclusive start, exclusive end), `constraints.remaining_days(session, soldier_id: uuid.UUID, today: date | None = None) -> dict` returning `{"cap_days": int, "used_days": int, "remaining_days": int, "period_start": date, "period_end": date}`.

- [ ] **Step 1: Write the failing test:**

```python
def test_period_bounds_quarter():
    assert constraints.period_bounds("quarter", date(2026, 8, 15)) == (date(2026, 7, 1), date(2026, 10, 1))

def test_period_bounds_half_year():
    assert constraints.period_bounds("half_year", date(2026, 8, 15)) == (date(2026, 7, 1), date(2027, 1, 1))

def test_period_bounds_year():
    assert constraints.period_bounds("year", date(2026, 8, 15)) == (date(2026, 1, 1), date(2027, 1, 1))

def test_remaining_days_counts_only_current_period(session, soldier_factory):
    s = soldier_factory()
    constraints.submit_constraint(session, soldier_id=s.id, start_date=date(2026, 1, 5), end_date=date(2026, 1, 10), reason="x")
    result = constraints.remaining_days(session, soldier_id=s.id, today=date(2026, 8, 1))
    assert result["used_days"] == 0
    assert result["remaining_days"] == result["cap_days"]

def test_remaining_days_counts_overlapping_current_period(session, soldier_factory):
    s = soldier_factory()
    constraints.submit_constraint(session, soldier_id=s.id, start_date=date(2026, 8, 3), end_date=date(2026, 8, 5), reason="x")
    result = constraints.remaining_days(session, soldier_id=s.id, today=date(2026, 8, 1))
    assert result["used_days"] == 3
    assert result["remaining_days"] == result["cap_days"] - 3
```

- [ ] **Step 2: Run test to verify it fails** — `pytest backend/tests/services/test_constraints.py -k "period_bounds or remaining_days" -v`.

- [ ] **Step 3: Implement** in `constraints.py`:

```python
def period_bounds(reset_period: str, today: date) -> tuple[date, date]:
    """Inclusive start / exclusive end of the reset period containing `today`."""
    if reset_period == "half_year":
        start_month = 1 if today.month <= 6 else 7
        start = date(today.year, start_month, 1)
        end = date(today.year, 7, 1) if start_month == 1 else date(today.year + 1, 1, 1)
        return start, end
    if reset_period == "year":
        return date(today.year, 1, 1), date(today.year + 1, 1, 1)
    q_start_month = ((today.month - 1) // 3) * 3 + 1
    start = date(today.year, q_start_month, 1)
    end_month = q_start_month + 3
    end = date(today.year, end_month, 1) if end_month <= 12 else date(today.year + 1, 1, 1)
    return start, end


def remaining_days(session: Session, *, soldier_id: uuid.UUID, today: date | None = None) -> dict:
    today = today or date.today()
    reset_period = str(_get_setting_with_default(session, "constraints.reset_period", "quarter"))
    period_start, period_end = period_bounds(reset_period, today)
    cap_days = int(_get_setting_with_default(session, "constraints.personal_cap_days", 15))
    rows = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == soldier_id,
            PersonalConstraint.status.in_(["pending", "approved"]),
            PersonalConstraint.start_date < period_end,
            PersonalConstraint.end_date >= period_start,
        )
    ).scalars().all()
    used = 0
    for r in rows:
        overlap_start = max(r.start_date, period_start)
        overlap_end = min(r.end_date, date.fromordinal(period_end.toordinal() - 1))
        used += (overlap_end - overlap_start).days + 1
    return {
        "cap_days": cap_days,
        "used_days": used,
        "remaining_days": max(0, cap_days - used),
        "period_start": period_start,
        "period_end": period_end,
    }
```

(Confirm `_get_setting_with_default` is the actual existing helper name in this file before using it — grep `constraints.py` for how `constraints.personal_cap_days` is currently read at line ~60 and reuse that exact helper/pattern instead of inventing a new one.)

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Route.** In `backend/app/routes/constraints.py`, add (mirroring the existing `GET /me/constraints` route's auth dependency):

```python
class RemainingDaysOut(BaseModel):
    cap_days: int
    used_days: int
    remaining_days: int
    period_start: date
    period_end: date


@router.get("/me/constraints/remaining", response_model=RemainingDaysOut)
def my_remaining_constraint_days(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RemainingDaysOut:
    return RemainingDaysOut(**constraints_svc.remaining_days(session, soldier_id=user.id))
```

(Match the exact dependency/import names already used by the neighboring `GET /me/constraints` route in this file — copy its `Depends(...)` signature verbatim rather than guessing.)

- [ ] **Step 6: Run** `pytest backend/tests/routes/test_constraints_routes.py -v` (or wherever constraint route tests live) to confirm no regressions from the new route.

- [ ] **Step 7: Commit** — `git add backend/app/services/constraints.py backend/app/routes/constraints.py backend/tests && git commit -m "feat: compute remaining personal-constraint days for the current reset period"`

### Task 5.2: Admin setting for reset period + frontend display

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx:25-26` (add a `constraints.reset_period` select next to the existing `constraints.personal_cap_days` entry)
- Modify: `frontend/src/api/constraints.ts` — add `getRemainingConstraintDays()`
- Modify: `frontend/src/pages/MyRequestsPage.tsx:181-188` — show the remaining/reset summary above the submit form
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1:** In `api/constraints.ts`, add:

```ts
export interface RemainingConstraintDays {
  cap_days: number;
  used_days: number;
  remaining_days: number;
  period_start: string;
  period_end: string;
}

export async function getRemainingConstraintDays(): Promise<RemainingConstraintDays> {
  const { data } = await api.get<RemainingConstraintDays>("/me/constraints/remaining");
  return data;
}
```

- [ ] **Step 2:** In `MyRequestsPage.tsx`, add a query and render a summary line directly above the submit form (around line 181):

```tsx
const remainingQuery = useQuery({
  queryKey: ["constraints", "remaining"],
  queryFn: getRemainingConstraintDays,
});
```

```tsx
{remainingQuery.data && (
  <p className="text-sm text-gray-600 dark:text-gray-300 mb-2">
    {t("constraints.remaining_summary", {
      remaining: remainingQuery.data.remaining_days,
      cap: remainingQuery.data.cap_days,
      until: formatDate(remainingQuery.data.period_end),
    })}
  </p>
)}
```

Invalidate the `["constraints", "remaining"]` query key alongside the existing constraint-list invalidation after a successful submit/cancel (find the existing `queryClient.invalidateQueries` call in this file's submit-mutation `onSuccess` and add the new key to the same call).

Add he.json key: `"remaining_summary": "נותרו {{remaining}} מתוך {{cap}} ימי אילוץ (עד {{until}})"` under a `constraints` section (create the section if it doesn't already exist — grep `he.json` for `"constraints"` first).

- [ ] **Step 3:** In `SystemSettingsPage.tsx`, add a select next to the existing `constraints.personal_cap_days` entry:

```tsx
{
  key: "constraints.reset_period",
  label: t("admin_settings.constraints_reset_period"),
  type: "select",
  options: [
    { value: "quarter", label: "רבעון" },
    { value: "half_year", label: "חצי שנה" },
    { value: "year", label: "שנה" },
  ],
  defaultValue: "quarter",
},
```

(Match this settings page's existing entry shape exactly — read the `constraints.personal_cap_days` entry immediately above it first and mirror its field names; the snippet above is illustrative of intent, not a literal copy of this file's actual settings-descriptor type.)

Add he.json key `"constraints_reset_period": "תקופת איפוס ימי אילוץ"` under `admin_settings`.

- [ ] **Step 4:** Manual check — as admin, set the reset period, submit a constraint as a soldier, confirm the remaining-days line appears above the submit form and updates after refetch.

- [ ] **Step 5: Commit** — `git add frontend/src/api/constraints.ts frontend/src/pages/MyRequestsPage.tsx frontend/src/pages/SystemSettingsPage.tsx frontend/src/i18n/he.json && git commit -m "feat: show remaining constraint days and admin reset-period setting"`

---

## Item 6 — Hide the Telegram notification column when Telegram is globally disabled

**Root cause (confirmed via research, differs from the surface-level bug report):** there is no separate "Telegram" column — the third preferences column is `push_enabled`, mislabeled `"בטלגרם"` in `he.json:923` (`"push": "בטלגרם"`), and today `push_enabled` genuinely is the only mechanism gating Telegram delivery (`backend/app/services/notifications.py:160`, `:296`, `:439` all check `pref.push_enabled` before calling `_enqueue_push`, which itself checks the global `telegram.enabled` setting). The bug is that `frontend/src/pages/ProfilePage.tsx` never reads the global `telegram.enabled` flag (already available via the existing `usePublicSettings()` hook, already used the same way in `frontend/src/components/TelegramBadge.tsx:8-9`) before rendering this column — so a meaningless toggle stays visible when Telegram is off system-wide.

### Task 6.1: Hide the push/Telegram preference column when Telegram is globally off

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx:456-493` (the preferences grid) and its imports

**Interfaces:**
- Consumes: `usePublicSettings()` from `frontend/src/hooks/usePublicSettings.ts` (existing, returns an object including `"telegram.enabled": boolean`).

- [ ] **Step 1:** Add the import and read the flag near the top of the component:

```tsx
import { usePublicSettings } from "../hooks/usePublicSettings";
```

```tsx
const publicSettings = usePublicSettings();
const telegramEnabled = publicSettings?.["telegram.enabled"] !== false;
```

- [ ] **Step 2:** In the preferences grid (around line 472), filter out `push_enabled` from the rendered field list when Telegram is disabled, instead of the current unconditional `(["in_app_enabled", "push_enabled", "email_enabled"] as const)` list:

```tsx
const prefColumns = (
  ["in_app_enabled", "push_enabled", "email_enabled"] as const
).filter((field) => field !== "push_enabled" || telegramEnabled);
```

Use `prefColumns` in place of the inline array literal at the existing `.map(...)` call site that builds the column headers/cells.

- [ ] **Step 3:** Manual check — as admin, turn `telegram.enabled` off in system settings, reload the profile page, confirm the push/Telegram column disappears from notification preferences; turn it back on, confirm it reappears.

- [ ] **Step 4: Commit** — `git add frontend/src/pages/ProfilePage.tsx && git commit -m "fix: hide push/Telegram notification column when Telegram is globally disabled"`

---

## Item 7 — Two untranslated notification-preference labels

**Root cause:** `he.json`'s `notifications.type_*` block (lines 938-960) is missing two keys used at `frontend/src/pages/ProfilePage.tsx:480` (`` t(`notifications.type_${p.notification_type}`) ``) for the `NotificationType` enum values `exemption_revoked` and `transfer_request_pending` (`backend/app/db/models.py:910-911`), so they render literally as `notifications.type_exemption_revoked` / `notifications.type_transfer_request_pending`.

### Task 7.1: Add the missing translations

**Files:**
- Modify: `frontend/src/i18n/he.json` (inside the existing `notifications.type_*` block, lines ~938-960)

- [ ] **Step 1:** Add the two missing keys, matching the phrasing style of neighboring `type_*` entries (e.g. `type_exemption_expiring`, `type_transfer_request_created` if present — check the block for the closest existing analog before wording these):

```json
"type_exemption_revoked": "פטור בוטל",
"type_transfer_request_pending": "בקשת העברה ממתינה",
```

- [ ] **Step 2:** Manual check — trigger (or find an existing soldier with) a notification preference row for each of these two types on the profile page; confirm both now show Hebrew text instead of the raw key.

- [ ] **Step 3: Commit** — `git add frontend/src/i18n/he.json && git commit -m "fix: add missing translations for two notification preference types"`

---

## Item 8 — Hierarchy page: show full tree, edit-gate and highlight per node

**Current behavior (confirmed via research):** `GET /hierarchy/tree` (`backend/app/routes/hierarchy.py:234-302`) server-side prunes the tree for non-admin, non-plain-soldier users to only nodes whose `path_ids` intersect the caller's `scope_root_ids` (commanded nodes + duty-manager scopes) — siblings/unrelated branches are never sent to the frontend at all. `frontend/src/components/HierarchyTree.tsx` renders whatever it receives (`renderNode`, lines 380-439), auto-expands only the first two path-depth levels regardless of the viewer (`useState` init at line 252), and gates every edit button (add child/soldier, assign commander, rename, delete — `DroppableNodeRow`, lines 214-243) on a single page-level `isAdmin` boolean, except the already-node-specific `dm_manageable` flag.

**Design:** stop pruning server-side — always return the full tree (matching the `admin`/`all` branch already used today). Add a per-node `can_edit: bool` to `NodeOut`, computed the same way `dm_manageable` already is, so the frontend can gate edit buttons per node instead of via the blanket `isAdmin` flag. On the frontend, compute the set of node ids the viewer commands (`node.commander_id === user.id`, plus any `dm_manageable` nodes) to (a) auto-expand every ancestor of those nodes on mount, and (b) apply a highlight class to those rows.

### Task 8.1: Backend — always return the full tree, add per-node `can_edit`

**Files:**
- Modify: `backend/app/routes/hierarchy.py:234-302` (`get_tree`), and wherever `NodeOut`/`_out()` is defined (same file, near line 37/122 per research)
- Test: `backend/tests/routes/test_hierarchy_routes.py`

**Interfaces:**
- Produces: `NodeOut.can_edit: bool` (true iff `user.role == "admin"` or `node.commander_id == user.id` or the node is already `dm_manageable` for this user); `GET /hierarchy/tree` now returns every `HierarchyNode` regardless of caller role (the `all`/scope-pruning branches collapse into one).

- [ ] **Step 1: Write the failing test:**

```python
def test_tree_returns_all_nodes_for_non_admin_commander(client, session, hierarchy_factory, commander_token, commander_id):
    own = hierarchy_factory.node(level="team", commander_id=commander_id)
    unrelated = hierarchy_factory.node(level="team")  # different branch, no relation to commander_id
    r = client.get("/hierarchy/tree", headers=auth_header(commander_token))
    ids = {n["id"] for n in r.json()}
    assert str(own.id) in ids
    assert str(unrelated.id) in ids  # previously excluded — now must be present

def test_tree_can_edit_flag_only_true_for_own_commanded_node(client, session, hierarchy_factory, commander_token, commander_id):
    own = hierarchy_factory.node(level="team", commander_id=commander_id)
    other = hierarchy_factory.node(level="team")
    r = client.get("/hierarchy/tree", headers=auth_header(commander_token))
    by_id = {n["id"]: n for n in r.json()}
    assert by_id[str(own.id)]["can_edit"] is True
    assert by_id[str(other.id)]["can_edit"] is False
```

- [ ] **Step 2: Run test to verify it fails** — `pytest backend/tests/routes/test_hierarchy_routes.py -k "returns_all_nodes or can_edit_flag" -v`.

- [ ] **Step 3: Implement.** In `get_tree`, replace the three-way branch (`admin`/`all`, plain `soldier`, pruned `else`) with a single unconditional full fetch:

```python
    nodes = list(session.execute(select(HierarchyNode)).scalars().all())
```

(Delete the now-dead `scope_root_ids`/`path_ids` filtering branch and the plain-`soldier` single-node branch entirely — confirm no other caller of this route relies on the pruned behavior before removing it; grep `hierarchy.py` and frontend `fetchTree` usages first.)

In the node-serialization helper (`_out()` near line 122, alongside where `dm_manageable` is already computed at lines 108-115 per research), add:

```python
    can_edit = user.role == "admin" or node.commander_id == user.id or dm_manageable
```

and include `can_edit=can_edit` in the constructed `NodeOut`. Add `can_edit: bool` to the `NodeOut` Pydantic model near line 37.

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Commit** — `git add backend/app/routes/hierarchy.py backend/tests && git commit -m "feat: hierarchy tree returns full tree with per-node can_edit flag"`

### Task 8.2: Frontend — auto-expand to and highlight the viewer's own node; gate edit buttons per node

**Files:**
- Modify: `frontend/src/api/hierarchy.ts` (add `can_edit` to the node type)
- Modify: `frontend/src/components/HierarchyTree.tsx:252` (expand-state init), `:214-243` (`DroppableNodeRow` edit-button gating), `:380-439` (`renderNode`, for the highlight class)
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx:27` (stop passing a blanket `isAdmin` for edit gating; keep it only for page-level actions like "create root node" that have no natural per-node home)

**Interfaces:**
- Consumes: `NodeOut.can_edit: bool` from Task 8.1.
- Produces: `HierarchyTree` no longer takes a blanket `isAdmin`-for-edit-buttons prop; each `DroppableNodeRow` reads `node.can_edit` directly. A new exported helper `ancestorIdsOf(nodes, targetId): string[]` in `HierarchyTree.tsx` (or a small new util file if the component file is already large) returns every ancestor id of a node using `path_ids`.

- [ ] **Step 1:** In `api/hierarchy.ts`, add `can_edit: boolean;` to the node interface returned by `fetchTree`.

- [ ] **Step 2:** In `HierarchyTree.tsx`, replace every `isAdmin && ...` / bare `isAdmin` condition in `DroppableNodeRow` (lines 214-243) with `node.can_edit && ...` / `node.can_edit`, keeping the existing `dm_manageable`-gated button as-is (now redundant with `can_edit` but harmless to leave — or fold it into the same `can_edit`-gated button block to avoid a duplicate control; prefer folding if the two buttons currently render distinctly for the same action).

- [ ] **Step 3:** Compute the viewer's own commanded node ids and their ancestors on mount/data-load, replacing the current `useState<Set<string>>` initializer (line 252) that only expands the first two levels:

```tsx
function ancestorIdsOf(nodes: NodeOut[], targetIds: Set<string>): Set<string> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const result = new Set<string>();
  for (const id of targetIds) {
    const node = byId.get(id);
    if (!node) continue;
    for (const ancestorId of node.path_ids) result.add(ancestorId);
  }
  return result;
}
```

```tsx
const ownNodeIds = useMemo(
  () => new Set(nodes.filter((n) => n.can_edit).map((n) => n.id)),
  [nodes],
);
const [expanded, setExpanded] = useState<Set<string>>(() => ancestorIdsOf(nodes, ownNodeIds));
```

(Keep the existing first-two-levels behavior as the fallback when `ownNodeIds` is empty, e.g. for a plain admin with no commanded node — `useMemo`/initializer should union with the old default rather than replacing it outright when `ownNodeIds.size === 0`.)

- [ ] **Step 4:** In `renderNode`, add a highlight class for rows in `ownNodeIds`:

```tsx
<div className={ownNodeIds.has(node.id) ? "bg-indigo-50 dark:bg-indigo-900/30 rounded" : undefined}>
```

wrapping (or added to the existing className string of) the row container already rendered per node.

- [ ] **Step 5:** In `TeamHierarchyPage.tsx`, remove the `isAdmin`-for-edit-gating prop passed into `HierarchyTree` (keep `isAdmin` only for page-level actions with no per-node home, e.g. a top-level "create root node" button, if one exists — check before removing entirely).

- [ ] **Step 6:** Manual check — log in as a non-admin section commander, open the hierarchy page, confirm: the full org tree is visible (not just their own branch); edit buttons (add child/soldier, assign commander, rename, delete) appear only on nodes they command; the tree is auto-expanded down to their own node; their own node's row is visually highlighted.

- [ ] **Step 7:** Run `npm run typecheck` from `frontend/` — expect 0 new errors.

- [ ] **Step 8: Commit** — `git add frontend/src/api/hierarchy.ts frontend/src/components/HierarchyTree.tsx frontend/src/pages/TeamHierarchyPage.tsx && git commit -m "feat: full hierarchy tree visibility with per-node edit gating, auto-expand and highlight own node"`

---

## Plan Self-Review Notes

- **Coverage:** all 8 feedback items map 1:1 to a numbered section above.
- **Item 4's test** references a shift-creation/listing helper whose exact name wasn't captured during research (only the buggy `dt_map.get` line numbers were) — Task 4.1 Step 1 explicitly calls out confirming the real function/test-module names before finalizing, rather than guessing at ones that don't exist.
- **Item 5** reuses the exact `period_bounds`/`remaining_days` design already scoped for the *previous* feedback batch's Item 3 (`docs/superpowers/plans/2026-07-21-feedback-batch-8-items.md`) — confirmed via research that batch was never executed (no `remaining_days`/`period_bounds`/route exists in the current codebase), so there is no conflict; if that older plan is executed first, Task 5.1 becomes a no-op verification pass instead of new work.
- **Item 8** intentionally removes rather than adds server-side filtering — flagged explicitly in Task 8.1 Step 3 to check for any other caller relying on the pruned response before deleting that branch.
