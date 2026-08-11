# Range eligibility warnings & status — design

Date: 2026-08-11

## Background

Follow-up to the 2026-08-10 (4) release. Three items from the original
range-eligibility request were not shipped (items 7, 9, 10), plus two
live-feedback asks surfaced afterward. All five share the same underlying
eligibility data model (`DutyEligibilityFact` / `weapon_eligibility.py` /
`ineligible_soldiers.py`), so they're designed and planned together.

## Scope

1. **Item 7** — soldier-scoped range-status section on `ProfilePage.tsx`
   (self-view) and `UnifiedSoldierModal.tsx`'s profile tab (viewing another
   soldier).
2. **Item 9** — richer weapon-ineligibility tooltip: show the soldier's most
   recent range qualification (type + date), even if expired, instead of
   just "why this duty is uncovered."
3. **Item 10** — info icon for soldiers who lack a currently valid
   qualification but have an upcoming primary range scheduled that would
   cover the requirement ("צפוי לעשות אל"ל ב11.11.26").
4. **Calendar event badges** (live feedback) — move the weapon-ineligibility
   warning (and new upcoming-coverage info signal) onto the calendar event
   itself as a badge, visible only to duty managers/commanders/admins.
   Remove the existing top-of-unit-calendar-page warning pill and filter
   status line.
5. **Homepage אל"ל warning** (live feedback) — only show the "אין אל"ל
   מעודכן" banner for soldiers who are actually relevant to duties requiring
   אל"ל (computed structurally, not via the current `is_officer`/`is_career`
   proxy), and cache that computation so it stays fast.

## Backend: shared query & data-model layer

### New query — latest qualification regardless of expiry

Every existing query in this pipeline
(`_max_qualification_valid_untils` in `weapon_eligibility.py`,
`_valid_qualifications_by_soldier` in `ineligible_soldiers.py`) filters
`valid_until >= as_of`, excluding expired qualifications entirely. Add a new
batched query, `_latest_qualification_by_soldier`, alongside
`_max_qualification_valid_untils` in `weapon_eligibility.py`:　

```python
def _latest_qualification_by_soldier(
    session, soldier_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, date]]:
    """Most recent SoldierRangeQualification per soldier, any validity state."""
```

Query `SoldierRangeQualification`, group by soldier, no `valid_until` filter,
ordered by `valid_until` descending, one `(range_type, valid_until)` row per
soldier (their most recent qualification of any type, expired or not).

### `DutyEligibilityFact` — two new fields

`backend/app/services/range_eligibility_projection.py`:

```python
@dataclass(frozen=True)
class DutyEligibilityFact:
    eligible: bool
    required_range_type: str | None
    qualification_source: str | None
    covered_by_range_date: date | None
    covering_range_type: str | None
    projected_valid_until: date | None
    reason: str | None
    last_qualification_type: str | None      # NEW
    last_qualification_date: date | None     # NEW — valid_until of most recent qualification, any state
```

Populated in `project_duty_eligibility` by merging in
`_latest_qualification_by_soldier`'s result. Both `None` means "never done a
qualifying range."

Item 10 needs **no new field** — `qualification_source == "planned_range"`,
`covered_by_range_date`, and `projected_valid_until` are already computed by
`_future_windows_by_soldier_and_required_type` and already flow into
`DutyEligibilityFact`. The info badge is a frontend read of existing data.

This one change surfaces richer data through every consumer of
`project_duty_eligibility`: the dashboard ineligible-soldiers panel, the new
item-7 endpoint, and calendar shift-assignee eligibility.

## Item 7 — soldier-scoped range-status endpoint

**Endpoint:** `GET /soldiers/{id}/range-status`

**Authorization:** self (`soldier.id == current_user.soldier_id`), or
duty-manager/commander/admin with the soldier in scope — reuse the
scope-check approach from `range_qualification_visibility.py`'s
`_resolve_roots`, applied to a single soldier.

**Response:** one entry per `required_range_type` tier relevant to the
soldier (mirroring the per-tier structure `_max_qualification_valid_untils`
already computes), assembled from the same building blocks
`project_duty_eligibility` uses but not tied to a specific duty assignment —
"status as of today, independent of any specific duty":

```json
{
  "soldier_id": "...",
  "statuses": [
    {
      "required_range_type": "alal",
      "eligible": false,
      "qualification_source": null,
      "last_qualification_type": "live",
      "last_qualification_date": "2026-03-01",
      "covered_by_range_date": "2026-11-11",
      "projected_valid_until": "2027-02-11"
    }
  ]
}
```

**Frontend:**
- `frontend/src/api/rangeStatus.ts` — thin typed wrapper, mirroring
  `ineligibleSoldiers.ts`'s style.
- `ProfilePage.tsx` — new `<section>` near the personal-details block
  (~line 240-420), rendered only if the soldier has at least one relevant
  `required_range_type` tier; reuses `formatRangeEligibilityExplanation`
  plus the new last-qualification text.
- `UnifiedSoldierModal.tsx` — same content added to the existing
  `"profile"` tab (already visible to self and to
  admin/duty_manager/commander per the existing `TABS` filtering — no new
  tab-visibility logic needed).

## Item 9 — richer tooltip (last range done)

`frontend/src/utils/rangeEligibilityExplanation.ts`: add a branch, used when
`qualification_source` is `null` (no current or planned coverage), before
the final `uncoveredDuty` fallback:

- `last_qualification_date == null` → `"אין מטווחים בתוקף"`
- `last_qualification_date` present → `"אין מטווחים בתוקף. מטווח אחרון - <type> ב<date>"`
  (dd.mm.yyyy, matching the existing Israeli-date formatting convention)

## Item 10 & calendar event badges — visual design

Two small icon badges rendered in `UnitCalendar.tsx`'s `eventContent`
callback, next to the existing swap-count badge (lines ~354-358), computed
once per shift from its `assignees` (`CalendarShiftAssignee[]`, which
already carries `weapon_ineligible` and `range_eligibility` per assignee):

- **Warning badge** (red ⚠, matching `ShiftDetailPanel`'s existing warning
  color): shown if `shift.assignees.some(a => a.weapon_ineligible)`.
  Tooltip: the `formatRangeEligibilityExplanation` text for the single
  ineligible assignee, or a count-based summary ("N חיילים לא כשירים") when
  more than one assignee is affected.
- **Info badge** (blue ℹ): shown only when there's no warning badge, and
  `shift.assignees.some(a => a.range_eligibility?.qualification_source === "planned_range")`.
  Tooltip: "צפוי לעשות <type> ב<date>" using `covered_by_range_date`.
- Both: `title` attribute only (hover, no click handler — matches existing
  pattern), rendered only when
  `user?.role === "admin" || user?.is_duty_manager || user?.is_commander`.

**Removing the top-of-page warning:**
- Delete the `weaponIneligibleCount` red pill and the
  `weaponIneligibleOnly`/`?filter=weapon_ineligible` status line from
  `UnitCalendar.tsx` (lines ~244-264).
- Remove the now-unused `getCalendarWeaponIneligibleCount` call in
  `api/calendar.ts` if nothing else references it (confirm during
  implementation before deleting).
- Leave `UnitCalendarPage.tsx`'s query-param handling alone unless it
  becomes fully dead — confirm whether `?filter=weapon_ineligible` is linked
  from elsewhere (e.g. the dashboard panel) before removing.

## Homepage אל"ל warning — compute + cache

**Computation:** a soldier is "אל"ל relevant" if their current hierarchy
node has any `DutyType` with `required_range_type == "alal"` reachable in
scope — structural, not date/schedule dependent. New helper,
`backend/app/services/alal_relevance.py`:

```python
def is_alal_relevant(session, soldier) -> bool
```

**Caching:** cache by `hierarchy_node_id → bool`, not by soldier — far fewer
distinct hierarchy nodes than soldiers, and the underlying fact only changes
when `DutyType` configuration changes. In-process dict cache, invalidated
explicitly wherever `DutyType` rows are created/updated/deleted (mirroring
the after-commit invalidation pattern already used for the
`weapon_ineligible` cache columns via `weapon_enforcement_changed` in
`settings_loader.py`). No TTL — invalidate-on-write, per project
convention for this kind of derived cache.

**Wiring:** add `alal_relevant: bool` to the same payload that already
supplies `is_officer`/`is_career`/`last_alal_date` to `useAuth()`'s `user`
(confirm exact endpoint during implementation — likely `/auth/me` or the
shared soldier-serialization helper). `AlertBanners.tsx`'s existing
`isAlalRelevant` gate changes from `user?.is_officer || user?.is_career` to
`user?.alal_relevant`. The existing date-math logic (`alertMessage`) is
unchanged — only the gate changes.

**Scope note:** does not touch `last_mitvahim_date`/the mitvahim banner —
only the אל"ל gate.

## Testing

- Backend: unit tests for `_latest_qualification_by_soldier` (never
  qualified / expired / current), the new `/soldiers/{id}/range-status`
  endpoint (self access, cross-soldier access with/without scope, 403 for
  out-of-scope), and `is_alal_relevant` + its cache invalidation on
  `DutyType` writes.
- Frontend: unit tests for the new `formatRangeEligibilityExplanation`
  branch, and for the calendar badge visibility logic (role-gating, warning
  vs. info precedence).
- Existing tests referencing the removed `weaponIneligibleCount` pill /
  `weaponIneligibleOnly` filter in `UnitCalendar.tsx` need updating or
  removal.

## Out of scope

- Changing how `last_mitvahim_date`/mitvahim banner works.
- Any change to the dashboard `IneligibleSoldiersPanel`/`IneligibleSoldiersTable`
  beyond automatically inheriting the new `DutyEligibilityFact` fields.
- TTL-based caching for the אל"ל relevance flag (using invalidate-on-write
  instead, per decision above).
