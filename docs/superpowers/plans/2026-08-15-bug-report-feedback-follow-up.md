# Bug Report Feedback Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address all eight active feedback reports exported in `C:\Users\Shoham\Downloads\bug-reports-2026-08-15-1420` while preserving the existing ranges, eligibility, profile, and feedback-report contracts.

**Architecture:** Keep range-event lifecycle transitions authoritative in the backend service and expose them through the existing range reads/worker. Keep configuration and presentation changes at their current seams: a dedicated range-locations tab, shared range-label/eligibility formatters, the profile auth refresh seam, and the app-shell scroll-container seam. No database migration is expected.

**Tech Stack:** FastAPI, SQLAlchemy, pytest; React 18, React Query, React Testing Library, Vitest, Tailwind CSS, `html-to-image`.

**Spec:** `C:\Users\Shoham\Downloads\bug-reports-2026-08-15-1420\index.md` and the eight Markdown reports in its `reports` directory.

## Global Constraints

- Keep Hebrew UI copy and English code identifiers.
- Use strict TDD: write a focused regression test, run it RED, make the minimal fix, then run it GREEN.
- Preserve unrelated staged, unstaged, and untracked work; do not commit directly to `master` or `dev`.
- A range with `date < today` and status `planned` becomes `completed`; today’s range remains `planned`, and `cancelled` is never rewritten.
- A range-location selector may use only centrally configured active locations; creation belongs in the range configuration tab, not the event form.
- Do not weaken permission checks or feature-flag route registration while changing tabs.
- Report focused checks separately from pre-existing full-suite or environment failures.

## Feedback coverage

| Report | Feedback | Planned task |
|---|---|---|
| `b7281384-8a7f-4964-8000-06fdefb8b6ce` | Past ranges remain `מתוכנן` | Task 1 |
| `50da91c1-f3f5-4935-906a-4330c5d07578` | Configure range locations in a tab under ranges, like duty locations | Task 2 |
| `deccd810-e94a-4b27-926a-80ef0503995f` | Range-type choices are unreadable/gray in the dark modal | Task 3 |
| `311dda6d-ba90-4495-b876-074191327e6f` | One-click copy for each invite code | Task 4 |
| `6f5a12ca-b612-41e5-b532-020142b04e68` | Approved last-range-date update is stale on profile | Task 5 |
| `9c4dc45e-abbd-4006-a36a-1beeefcade02` | Remove empty “no range required” banner; show actual duty requirements | Task 6 |
| `11e0ad97-5fc8-47d4-b383-f93012777e4e` | Put “אין מטווחים בתוקף” on a separate line/better format | Task 7 |
| `e46d7670-8ae3-43d5-9760-da149856a1f1` | Feedback HTML-to-image captures the top instead of the scrolled content | Task 8 |

## File map

- Backend lifecycle: `backend/app/services/ranges.py`, `backend/app/routes/ranges.py`, `backend/app/range_attendance_worker.py`, new `backend/app/services/tests/test_range_event_status.py`.
- Range configuration/form: `frontend/src/pages/RangesPage.tsx`, new `frontend/src/components/ranges/RangeLocationsContent.tsx`, `frontend/src/components/ranges/RangeLocationsContent.test.tsx`, `frontend/src/components/ranges/RangeFormModal.tsx`, `frontend/src/components/ranges/RangeFormModal.test.tsx`, `frontend/src/pages/RangesPage.test.tsx`.
- Invite codes: `frontend/src/pages/AdminInviteCodesPage.tsx`, new `frontend/src/pages/AdminInviteCodesPage.test.tsx`.
- Profile freshness: `frontend/src/pages/ProfilePage.tsx`, new `frontend/src/pages/ProfilePage.test.tsx`.
- Duty requirements: `frontend/src/components/ShiftDetailPanel.tsx`, new `frontend/src/utils/dutyRequirements.ts`, new `frontend/src/utils/dutyRequirements.test.ts`, `frontend/src/components/ShiftDetailPanel.test.tsx`, `frontend/src/api/dutyConfig.ts` if the current requirement type needs widening.
- Eligibility copy: `frontend/src/utils/rangeEligibilityExplanation.ts`, `frontend/src/utils/rangeEligibilityExplanation.test.ts`, `frontend/src/components/ShiftDetailPanel.tsx`, `frontend/src/components/UnitCalendar.tsx` only if the calendar badge needs a matching explicit tooltip.
- Feedback capture: `frontend/src/components/Layout.tsx`, `frontend/src/components/BugReportTrigger.tsx`, `frontend/src/components/BugReportTrigger.test.tsx`, `frontend/src/styles/globals.css`.

---

### Task 1: Transition elapsed planned ranges to completed

**Files:**
- Modify: `backend/app/services/ranges.py`
- Modify: `backend/app/routes/ranges.py`
- Modify: `backend/app/range_attendance_worker.py`
- Create: `backend/app/services/tests/test_range_event_status.py`

**Interfaces:**
- Produce `mark_past_range_events_completed(session: Session, *, today: date | None = None) -> int`.
- The helper updates only `RangeEventStatus.planned` rows with `RangeEvent.date < today`, writes the existing audit format, and is idempotent.

- [ ] **Step 1: Write the failing service regression.** Create a past planned event, a today planned event, a future planned event, and a cancelled past event; call the helper with a fixed date and assert only the past planned event becomes `completed` and the return count is `1`.
- [ ] **Step 2: Run the focused backend test.**

  Run: `backend\.venv\Scripts\python.exe -m pytest backend/app/services/tests/test_range_event_status.py -q`

  Expected: FAIL because the helper does not exist.
- [ ] **Step 3: Implement the idempotent transition.** Select only planned rows before the supplied/current date, set `completed`, write one `range_event.complete` audit entry per changed event, flush the session, and return the number changed.
- [ ] **Step 4: Add read and worker integration.** Invoke the helper before `/ranges` list/detail serialization and from the range-attendance worker’s session so the UI is corrected immediately and unattended operation persists the state. Do not change cancelled events or attendance semantics.
- [ ] **Step 5: Add route/worker regression coverage.** Assert a past event is returned as `completed`, and a second transition call changes nothing. Keep update/assignment guards rejecting a now-completed event through the existing `event_not_planned` contract.
- [ ] **Step 6: Run focused verification.**

  Run: `backend\.venv\Scripts\python.exe -m pytest backend/app/services/tests/test_range_event_status.py backend/app/services/tests/test_range_attendance_auto_mark.py -q`

- [ ] **Step 7: Commit on the feature branch.** `git commit -m "fix: complete elapsed range events"`

### Task 2: Add a dedicated range-locations configuration tab

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Create: `frontend/src/components/ranges/RangeLocationsContent.tsx`
- Create: `frontend/src/components/ranges/RangeLocationsContent.test.tsx`
- Modify: `frontend/src/components/ranges/RangeFormModal.tsx`
- Modify: `frontend/src/components/ranges/RangeFormModal.test.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`

**Interfaces:**
- `RangeLocationsContent` consumes `RangeLocation[]`, `onCreate(name: string)`, and loading/error state; it renders the configured-location list and manager-only create form in the same compact pattern as `DutyConfigContent`.
- The event form consumes centrally fetched locations through `RangesPage` and no longer creates locations inline.

- [ ] **Step 1: Write the failing component tests.** Assert that `?tab=locations` renders a `מיקומי מטווחים` tab/panel, lists existing locations, creates a new location through `createRangeLocation`, and that the event form has no `+ הוסף מיקום` control.
- [ ] **Step 2: Run the focused frontend tests.**

  Run from `frontend`: `npx vitest run src/components/ranges/RangeLocationsContent.test.tsx src/components/ranges/RangeFormModal.test.tsx src/pages/RangesPage.test.tsx`

  Expected: FAIL because the tab and centralized form do not exist.
- [ ] **Step 3: Implement the tab state.** Extend the existing `tab=ineligible` query contract with `tab=locations`; keep `/ranges` registered unconditionally, preserve the existing schedule/qualification tabs, and avoid fetching planning rows when the locations tab is active.
- [ ] **Step 4: Implement the configuration panel.** Reuse `listRangeLocations`/`createRangeLocation` and `queryKeys.rangeLocations()`, show the location list and a validated Hebrew-name create form to managers, and keep read access aligned with the existing range-location GET permission.
- [ ] **Step 5: Remove inline creation.** Keep `RangeFormModal` as a selector only, pass the fetched list into the existing `Combobox`, and show the existing “יש לבחור מיקום” validation when no location is selected.
- [ ] **Step 6: Run focused verification.**

  Run from `frontend`: `npx vitest run src/components/ranges/RangeLocationsContent.test.tsx src/components/ranges/RangeFormModal.test.tsx src/pages/RangesPage.test.tsx && npm run typecheck`

- [ ] **Step 7: Commit.** `git commit -m "feat: centralize range location configuration"`

### Task 3: Make range-type choices readable in the dark modal

**Files:**
- Modify: `frontend/src/components/ranges/RangeFormModal.tsx`
- Modify: `frontend/src/components/ranges/RangeFormModal.test.tsx`
- Modify: `frontend/src/utils/rangeLabels.ts` only if the options are moved to a shared typed list.

- [ ] **Step 1: Write the failing UI regression.** Focus the range-type control and assert the list visibly contains `מטווח לייזר`, `מטווח חי`, and `אל"ל`, with the selected value rendered as the Hebrew label rather than a raw enum or gray native option.
- [ ] **Step 2: Run the focused test and confirm RED.**

  Run from `frontend`: `npx vitest run src/components/ranges/RangeFormModal.test.tsx -t "range type"`

- [ ] **Step 3: Replace the dark-native select with the shared styled `Combobox`** using items `{ id: "laser", name: "מטווח לייזר" }`, `{ id: "live", name: "מטווח חי" }`, and `{ id: "alal", name: "אל"ל" }`; preserve the controlled `RangeType` value and form submission payload.
- [ ] **Step 4: Run focused verification.**

  Run from `frontend`: `npx vitest run src/components/ranges/RangeFormModal.test.tsx src/components/Combobox.test.tsx && npm run typecheck`

- [ ] **Step 5: Commit.** `git commit -m "fix: show readable range type choices"`

### Task 4: Add one-click invite-code copying

**Files:**
- Modify: `frontend/src/pages/AdminInviteCodesPage.tsx`
- Create: `frontend/src/pages/AdminInviteCodesPage.test.tsx`

**Interface:** Each active or revoked code row has an accessible button that calls `navigator.clipboard.writeText(code)` and gives a temporary Hebrew success state; a rejected/unavailable clipboard call leaves the code visible and shows an actionable failure state without affecting revoke behavior.

- [ ] **Step 1: Write the failing tests.** Mock `listInviteCodes`, render a row, click its copy button, assert the exact code is passed to `navigator.clipboard.writeText`, assert the success label appears, and assert a rejected clipboard call shows an error while the row remains usable.
- [ ] **Step 2: Run the focused test and confirm RED.**

  Run from `frontend`: `npx vitest run src/pages/AdminInviteCodesPage.test.tsx`

- [ ] **Step 3: Add the copy action.** Place a small `type="button"` beside the code, with an explicit `aria-label`/tooltip, local copied/error state keyed by code id, and no mutation or navigation side effects.
- [ ] **Step 4: Run focused verification.** `npx vitest run src/pages/AdminInviteCodesPage.test.tsx && npm run typecheck`
- [ ] **Step 5: Commit.** `git commit -m "feat: copy invite codes from admin settings"`

### Task 5: Refresh the authenticated profile after approved field updates

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx`
- Create: `frontend/src/pages/ProfilePage.test.tsx`

- [ ] **Step 1: Write the failing profile regression.** Mock `useAuth` with an old `last_mitvahim_date` and a `refreshMe` spy, render the page, and assert the page requests a fresh `/me` value when the profile route mounts; then rerender with the new date and assert the new date is displayed.
- [ ] **Step 2: Run the focused test and confirm RED.** `npx vitest run src/pages/ProfilePage.test.tsx`
- [ ] **Step 3: Refresh at the page seam.** Call `refreshMe()` once when `ProfilePage` mounts or becomes active, catch network failure without breaking the profile, and leave the existing 60-second `AuthContext` polling as a background fallback.
- [ ] **Step 4: Verify the approval path.** Add/retain a backend service assertion that approving `last_mitvahim_date` mutates `Soldier.last_mitvahim_date`; the frontend regression then proves the stale-auth-cache half of the report.
- [ ] **Step 5: Run focused verification.** `npx vitest run src/pages/ProfilePage.test.tsx && backend\.venv\Scripts\python.exe -m pytest backend/app/services/tests/test_soldiers.py -q && npm run typecheck`
- [ ] **Step 6: Commit.** `git commit -m "fix: refresh profile data after approval"`

### Task 6: Show only meaningful duty requirements in the shift detail panel

**Files:**
- Modify: `frontend/src/components/ShiftDetailPanel.tsx`
- Create: `frontend/src/utils/dutyRequirements.ts`
- Create: `frontend/src/utils/dutyRequirements.test.ts`
- Modify: `frontend/src/components/ShiftDetailPanel.test.tsx`
- Modify: `frontend/src/api/dutyConfig.ts` only if the response type omits a field already returned by the backend.

**Interface:** `formatDutyRequirements(dutyType: DutyType | undefined, requiredRangeType: string | null): string[]` returns ordered, display-ready Hebrew requirement labels and returns `[]` when the duty has no requirements.

- [ ] **Step 1: Write the failing formatter tests.** Cover no requirements, a required range type, military driving license, and combined requirements; assert stable order and no duplicate generic/range labels.
- [ ] **Step 2: Run the focused formatter and panel tests.** `npx vitest run src/utils/dutyRequirements.test.ts src/components/ShiftDetailPanel.test.tsx`
- [ ] **Step 3: Implement the formatter.** Read `DutyType.requirements`, `required_range_type`, and the existing `RANGE_TYPE_LABELS`; include only active constraints such as a specific range, military driving license, מטווחים/אל"ל/בה"ד 1, rank/service/gender restrictions where present.
- [ ] **Step 4: Replace the unconditional top banner.** Render nothing when the formatter returns no labels; otherwise render a compact requirement panel with one line/list item per requirement. Keep eligibility badges and permission gating unchanged.
- [ ] **Step 5: Add panel regressions.** Assert the empty-duty case has no `noRequiredRange` copy, and a duty requiring a military license plus a laser range shows both Hebrew requirements.
- [ ] **Step 6: Run focused verification.** `npx vitest run src/utils/dutyRequirements.test.ts src/components/ShiftDetailPanel.test.tsx && npm run typecheck`
- [ ] **Step 7: Commit.** `git commit -m "fix: show meaningful duty requirements"`

### Task 7: Format eligibility explanations with a separate expiry/qualification line

**Files:**
- Modify: `frontend/src/utils/rangeEligibilityExplanation.ts`
- Modify: `frontend/src/utils/rangeEligibilityExplanation.test.ts`
- Modify: `frontend/src/components/ShiftDetailPanel.tsx`
- Modify: `frontend/src/components/UnitCalendar.tsx` if the calendar event tooltip needs the same explicit line break.

- [ ] **Step 1: Write the failing copy/rendering tests.** Assert the uncovered explanation contains a line break before `אין מטווחים בתוקף`, and the warning popover uses `white-space: pre-line` so the break is visible rather than collapsed.
- [ ] **Step 2: Run the focused tests and confirm RED.** `npx vitest run src/utils/rangeEligibilityExplanation.test.ts src/components/ShiftDetailPanel.test.tsx`
- [ ] **Step 3: Implement the copy contract.** Return the main duty-requirement sentence and the current/never-qualified clause separated by `\n`, and render the explanation in a `whitespace-pre-line` element. Keep the native `title` fallback readable for calendar badges.
- [ ] **Step 4: Add the zero/current qualification cases.** Ensure `אין מטווחים בתוקף` is its own line when no qualification exists, while a known last qualification remains a separate date/type line and planned-range coverage keeps its existing meaning.
- [ ] **Step 5: Run focused verification.** `npx vitest run src/utils/rangeEligibilityExplanation.test.ts src/components/ShiftDetailPanel.test.tsx src/components/UnitCalendar.test.tsx && npm run typecheck`
- [ ] **Step 6: Commit.** `git commit -m "fix: format range eligibility warning details"`

### Task 8: Capture the app’s actual scroll container in feedback screenshots

**Files:**
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/components/BugReportTrigger.tsx`
- Modify: `frontend/src/components/BugReportTrigger.test.tsx`
- Modify: `frontend/src/styles/globals.css`

**Interface:** `Layout` exposes a marked app scroll container and a marked scroll-content wrapper. `BugReportTrigger` reads `scrollTop`/`scrollLeft` from that element and passes capture-only CSS variables so the cloned scroll content is translated inside its unchanged viewport; it falls back to window scroll values for non-shell pages.

- [ ] **Step 1: Write the failing regression.** Render a marked `main` with `scrollTop = 300` and `scrollLeft = 40`, click feedback, and assert `toPng` receives capture-only `--bug-report-scroll-top: -300px` and `--bug-report-scroll-left: -40px`; assert the existing window-scroll fallback remains covered.
- [ ] **Step 2: Run the focused test and confirm RED.** `npx vitest run src/components/BugReportTrigger.test.tsx`
- [ ] **Step 3: Add stable shell markers.** Wrap `Layout`’s children in a scroll-content element and mark the existing `<main>` as the app scroll container without changing its height, overflow, or padding contract.
- [ ] **Step 4: Apply clone-only translation.** Read the app container offsets before asynchronous capture, pass CSS variables in the `html-to-image` `style` option, and add a global rule that translates only the marked cloned content. Do not mutate the live page’s scroll position and do not translate the fixed header.
- [ ] **Step 5: Add a browser-level repro check.** Use the existing Playwright setup to scroll a long profile page’s app `main`, open feedback, decode/inspect the captured image or compare a known lower-page marker, and assert the screenshot contains the lower marker rather than only the header. Keep capture timeout behavior and modal opening on failure unchanged.
- [ ] **Step 6: Run focused verification.** `npx vitest run src/components/BugReportTrigger.test.tsx && npm run typecheck && npm run test:e2e -- --grep "feedback|screenshot"`
- [ ] **Step 7: Commit.** `git commit -m "fix: capture feedback screenshots at current scroll"`

## Final integration and verification

- [ ] Review `git diff --check` and `git status --short`; confirm the plan’s changes do not include `.release-git/` or unrelated WIP.
- [ ] Run all focused frontend tests together:

  `cd frontend; npx vitest run src/pages/RangesPage.test.tsx src/components/ranges/RangeFormModal.test.tsx src/components/ranges/RangeLocationsContent.test.tsx src/pages/AdminInviteCodesPage.test.tsx src/pages/ProfilePage.test.tsx src/components/ShiftDetailPanel.test.tsx src/components/BugReportTrigger.test.tsx src/utils/dutyRequirements.test.ts src/utils/rangeEligibilityExplanation.test.ts`

- [ ] Run all focused backend tests together:

  `backend\.venv\Scripts\python.exe -m pytest backend/app/services/tests/test_range_event_status.py backend/app/services/tests/test_range_attendance_auto_mark.py backend/app/services/tests/test_soldiers.py -q`

- [ ] Run `cd frontend; npm run typecheck; npm run lint` and report any pre-existing warnings separately from touched-file failures.
- [ ] If the full backend suite is run, report parser/OCR, Docker named-pipe, timeout, or port failures as environment/unrelated blockers rather than calling the suite green.
- [ ] Manually verify all eight report scenarios against the supplied screenshots: ranges status, range-location tab, range-type dropdown, invite-code copy, approved profile date, duty requirement panel, multiline warning explanation, and scrolled feedback capture.
- [ ] Request code review before integration; merge the feature branch into `dev` only through the project `merge-worktree-to-dev` skill.

## Self-review checklist

- Coverage: all eight report IDs appear in the feedback matrix and map to a task with a focused regression.
- Placeholder scan: no `TBD`, `TODO`, or unspecified “handle edge cases” steps remain.
- Contract consistency: the range-location tab uses `queryKeys.rangeLocations()`, the form remains selector-only, and `RangeType` values stay `laser | live | alal` across API and UI.
- Verification: every task has a RED command, a GREEN command, and a final integration check.
