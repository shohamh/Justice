# Range Eligibility Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing algorithm-backed weapon-range eligibility understandable to planners and commanders everywhere duties and calendars are viewed, while removing the standalone weapon-ineligibility nav item.

**Architecture:** Add a backend projection layer around `compute_eligibility`/`bulk_ineligible_duty_blocks` that returns per-duty eligibility facts and scoped unique-soldier counts. Share one frontend formatter and hierarchy table between the ranges tab and commander dashboard; calendar and shift-detail consumers use the same per-duty facts. Keep all UI informational and preserve backend authorization gates.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React, TypeScript, TanStack Query, Vitest, Testing Library, Tailwind, react-i18next.

## Global Constraints

- Evaluate eligibility on the duty's scheduled date.
- Qualification tiers are hierarchical: אל״ל > מטווח חי > מטווח לייזר.
- Future coverage uses planned, non-reserve, non-draft main assignments, configured validity windows, and pending-excusal settings exactly as `backend/app/services/weapon_eligibility.py`.
- No UI action in this feature assigns a range, changes a qualification, or changes a duty assignment.
- Remove `nav-weapon-ineligible`; do not add a חוסר כשירות destination.
- All new user-facing strings must be in `frontend/src/i18n/he.json`.
- Preserve unrelated user WIP, especially `logs/backend.log.1` in the main worktree.

---

### Task 1: Shared backend eligibility projection and scoped counts

**Files:**
- Modify: `backend/app/services/weapon_eligibility.py`
- Create: `backend/app/services/range_eligibility_projection.py`
- Create: `backend/app/services/tests/test_range_eligibility_projection.py`
- Modify: `backend/app/routes/range_qualification_visibility.py`
- Modify: `backend/tests/integration/test_ineligible_soldiers_api.py`

**Interfaces:**
- `project_duty_eligibility(session, *, soldier_ids: Sequence[UUID], duty_ids: Sequence[UUID], as_of: date | None = None) -> dict[tuple[UUID, UUID], DutyEligibilityFact]`
- `count_ineligible_soldiers_for_duties(session, *, soldier_ids: Sequence[UUID], duty_ids: Sequence[UUID], as_of: date | None = None) -> int`
- `DutyEligibilityFact` contains `eligible`, `required_range_type`, `qualification_source`, `covered_by_range_date`, `projected_valid_until`, and `reason`.
- Extend existing planning/commander response records with per-duty explanation facts without changing authorization derivation.

- [ ] **Step 1: Write failing service tests**

Cover exact-tier and higher-tier qualification, qualification expiry on the duty date, planned main-range projected coverage, reserve/draft exclusion, pending excusal behavior, disabled enforcement, two duties with different requirements, and unique-soldier counting.

- [ ] **Step 2: Run the focused service tests and verify failure**

Run from `backend/`: `pytest app/services/tests/test_range_eligibility_projection.py -q`.

- [ ] **Step 3: Implement the projection by delegating to existing eligibility primitives**

Use `_qualification_types_at_or_above`, `_max_qualification_valid_until`, `_future_windows`, and `_is_eligible_from_data`; do not create a second tier map or window calculation. Batch database reads by soldier and required tier.

- [ ] **Step 4: Add/extend scoped API response fields and count behavior**

Planning responses use duty-manager roots, commander responses use commander subtrees, and overlapping roots remain deduplicated. Add a dedicated per-duty/count route only where calendar and shift consumers cannot reuse an existing response.

- [ ] **Step 5: Run focused backend tests and commit**

Run `pytest app/services/tests/test_range_eligibility_projection.py tests/integration/test_ineligible_soldiers_api.py -q` and Ruff/format checks. Commit with `feat: add shared range eligibility projection`.

---

### Task 2: Shared explanations and sortable hierarchy table

**Files:**
- Create: `frontend/src/utils/rangeEligibilityExplanation.ts`
- Create: `frontend/src/utils/rangeEligibilityExplanation.test.ts`
- Modify: `frontend/src/api/ineligibleSoldiers.ts`
- Modify: `frontend/src/components/ranges/IneligibleSoldiersTable.tsx`
- Modify: `frontend/src/components/ranges/IneligibleSoldiersTable.test.tsx`
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/i18n/he.json`

**Interfaces:**
- `formatRangeEligibilityExplanation(fact: DutyEligibilityFact, t: TFunction): string`
- `IneligibleSoldiersTable` accepts the extended response and continues to support `DataTable` sorting/expansion.

- [ ] **Step 1: Write failing formatter and table tests**

Assert exact Hebrew output for no current qualification, no weapon duty, uncovered duty, and future planned-range coverage. Assert sorting by hierarchy, soldier, qualification, and future context using header interactions, plus stable expansion and empty/error states.

- [ ] **Step 2: Run the focused frontend tests and verify failure**

Run from `frontend/`: `npm test -- src/utils/rangeEligibilityExplanation.test.ts src/components/ranges/IneligibleSoldiersTable.test.tsx`.

- [ ] **Step 3: Implement the shared formatter and sortable columns**

Use `dd.mm.yyyy` formatting and existing range-type translations. Use the exact copy: `אין מטווחים בתוקף`, `טרם שובץ לתורנות שדורשת נשק`, and the duty/range/date explanation approved in the spec.

- [ ] **Step 4: Run focused tests, lint, and typecheck**

Run the focused Vitest files, `npm run lint`, and `npm run typecheck`.

- [ ] **Step 5: Commit**

Commit with `feat: explain range eligibility in sortable table`.

---

### Task 3: Commander dashboard reuses the hierarchy table

**Files:**
- Modify: `frontend/src/components/dashboard/IneligibleSoldiersPanel.tsx`
- Modify: `frontend/src/components/dashboard/IneligibleSoldiersPanel.test.tsx`
- Modify: `frontend/src/pages/CommandDashboardPage.tsx`
- Modify: `frontend/src/pages/CommandDashboardPage.test.tsx`

**Interfaces:**
- `IneligibleSoldiersPanel` renders the shared hierarchy table with `audience="commander"`; it does not render per-soldier cards.

- [ ] **Step 1: Write failing dashboard reuse tests**

Assert the dashboard renders hierarchy rows, expandable soldier rows, sortable columns, shared exact explanations, commander-scoped data, and loading/error/empty states.

- [ ] **Step 2: Implement table reuse**

Move only shared presentation into the table component; keep dashboard-specific query and panel wiring thin. Do not introduce assignment or qualification actions.

- [ ] **Step 3: Run focused tests and commit**

Run `npm test -- src/components/dashboard/IneligibleSoldiersPanel.test.tsx src/pages/CommandDashboardPage.test.tsx src/components/ranges/IneligibleSoldiersTable.test.tsx`, lint, and typecheck. Commit with `feat: reuse range eligibility table on commander dashboard`.

---

### Task 4: Navigation badge aggregation and standalone-item removal

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx`
- Modify: `frontend/src/components/UnifiedNav.test.tsx`
- Modify: `frontend/src/i18n/he.json` for aggregate badge accessibility text

- [ ] **Step 1: Write failing nav tests**

Assert `nav-weapon-ineligible` is absent for every role, the existing מטווחים item keeps its badge, תכנון receives the aggregate count, parent items sum child counts, and the worst color is selected in red > orange > blue > green order.

- [ ] **Step 2: Implement a small parent-badge aggregation helper**

Represent each child badge as `{ count, color }`, aggregate counts by parent, and render one badge per parent item without creating a new destination. Preserve existing pending/algorithm badges and query gating.

- [ ] **Step 3: Run focused tests and commit**

Run `npm test -- src/components/UnifiedNav.test.tsx`, lint, and typecheck. Commit with `fix: aggregate range warnings in navigation`.

---

### Task 5: Calendar counts, filters, and event hover affordances

**Files:**
- Modify: `backend/app/routes/calendar.py`
- Modify: `backend/app/services/calendar_shifts.py`
- Create/modify: backend calendar route/service tests
- Modify: `frontend/src/api/calendar.ts`
- Modify: `frontend/src/components/UnitCalendar.tsx`
- Modify: `frontend/src/components/UnitCalendar.test.tsx`
- Modify: `frontend/src/pages/UnitCalendarPage.tsx`
- Create: `frontend/src/pages/UnitCalendarPage.test.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Write failing backend calendar tests**

Assert scoped unique-soldier warning counts, duty-date projection, and no count for non-weapon duties or soldiers covered by a planned main range.

- [ ] **Step 2: Write failing frontend tests**

Assert the red warning-icon badge appears with the unique count, the duty-type filter renders when there are no assigned duties, and event elements have pointer cursor plus light/dark hover classes.

- [ ] **Step 3: Implement calendar count and visual behavior**

Keep count failures non-blocking and hide the badge while loading or on error. Preserve existing filters, selected-shift behavior, and the range filter. Use stable classes that work in both themes.

- [ ] **Step 4: Run focused checks and commit**

Run `pytest tests/integration/test_calendar_api.py -q` and `npm test -- src/components/UnitCalendar.test.tsx src/pages/UnitCalendarPage.test.tsx` plus `npm run lint` and `npm run typecheck`. Commit with `feat: show range eligibility warnings in calendars`.

---

### Task 6: Shift-detail required tier and soldier warnings

**Files:**
- Modify: `backend/app/routes/calendar.py`
- Modify: `backend/app/routes/shifts.py` to expose required-tier and per-assignee eligibility facts when the selected shift is loaded
- Modify: `frontend/src/api/calendar.ts`
- Modify: `frontend/src/components/ShiftDetailPanel.tsx`
- Modify: `frontend/src/components/ShiftDetailPanel.test.tsx`
- Modify: `backend/tests/integration/test_calendar_api.py`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Write failing shift-detail tests**

Assert the required tier appears in the detail header and each ineligible assignee gets a red warning-icon badge and shared explanation; eligible assignees do not. Assert the missing-fact neutral state.

- [ ] **Step 2: Implement per-duty shift facts**

Have the backend calculate eligibility for the selected shift date and required tier. Keep reserve/primary display behavior unchanged and do not mutate assignment data.

- [ ] **Step 3: Run focused tests and commit**

Run `npm test -- src/components/ShiftDetailPanel.test.tsx`, `pytest tests/integration/test_calendar_api.py -q`, lint, and typecheck. Commit with `feat: show range warnings in shift details`.

---

### Task 7: Upcoming duty details and forced-callup gate

**Files:**
- Modify: `frontend/src/components/UpcomingSnapshot.tsx`
- Modify: `frontend/src/components/UpcomingSnapshot.test.tsx`
- Modify: `frontend/src/components/dashboard/DutyDetailModal.tsx` to reuse the existing duty-detail presentation
- Modify: `frontend/src/api/commanderDashboard.ts` to expose the shift/location identifiers needed by the detail action
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Write failing tests**

Assert `שחרור פיקודי` is absent when `forced_callup.enabled` is false, present when true, and `צפה בפרטי התורנות` opens the existing duty detail with duty name, dates, location, and required range tier.

- [ ] **Step 2: Implement the setting gate and detail action**

Use the existing public settings hook and existing duty-detail modal/query. Do not duplicate release mutations or create a second duty-detail UI.

- [ ] **Step 3: Run focused tests and commit**

Run `npm test -- src/components/UpcomingSnapshot.test.tsx`, lint, and typecheck. Commit with `fix: gate commander release and show duty details`.

---

### Task 8: Regression verification and handoff

**Files:** none unless a regression is found in the task files above.

- [ ] **Step 1: Run all focused feature suites**

Run the projection/API backend tests and all new/changed frontend tests together.

- [ ] **Step 2: Run broad checks**

From `frontend/`, run `npm test`, `npm run lint`, and `npm run typecheck`. From `backend/`, run `pytest -q`. Classify infrastructure or pre-existing warnings separately.

- [ ] **Step 3: Inspect final diff and worktree**

Run `git diff --check`, `git diff dev...HEAD --stat`, and `git status --short`; preserve unrelated WIP.

- [ ] **Step 4: Request final two-axis review**

Review the full branch against `docs/superpowers/specs/2026-08-09-range-eligibility-guidance-design.md`, resolve findings, and report the final branch tip without merging or pushing unless explicitly requested.
