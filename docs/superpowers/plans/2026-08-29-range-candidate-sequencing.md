# Range Candidate Sequencing and Automatic Refill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make range candidate ranking and future range rosters time-aware, distinguishing primary/reserve assignments and excusal status, and automatically remove duplicate future assignments and refill their slots.

**Architecture:** Add one shared read-only range-coverage query seam that answers whether a soldier has valid current coverage, a future primary range, or only reserve-like coverage for a given duty date. Reuse it in candidate ranking and weapon-duty eligibility. Add a transactional reconciliation service invoked after range assignment and primary-excusal decisions; it removes only redundant later assignments and refills their primary/reserve slots through the existing candidate and assignment validation paths.

**Tech Stack:** Python, SQLAlchemy, FastAPI services, PostgreSQL, pytest; existing React/Vitest candidate UI and query invalidation.

**Spec:** Approved requirements from the 2026-08-29 range-candidate rules discussion; current implementation references `backend/app/services/range_auto_assign.py`, `backend/app/services/range_excusal.py`, and `backend/app/services/weapon_eligibility.py`.

## Global Constraints

- Preserve the existing authorized-scope, exemption, structural-eligibility, same-day conflict, personal-constraint, capacity, and audit rules.
- A planned primary range counts as future qualification only when it has no pending excusal request; a pending-excusal primary is reserve-like.
- A reserve range counts as coverage only after call-up/confirmation; a draft never counts and never triggers reconciliation.
- A range after the current event can cover a later duty, but never an earlier duty.
- Automatic reconciliation applies only to confirmed/planned assignments and must leave an explicit shortage when no replacement exists.
- Keep primary and reserve slots distinct; never refill a primary slot with a reserve assignment or vice versa.
- Preserve unrelated dirty worktree changes and use focused RED -> GREEN tests before implementation.

## File Map

- Create: `backend/app/services/range_coverage.py` — shared date-aware coverage classification and bulk lookup for range assignments, qualifications, and excusal state.
- Modify: `backend/app/services/range_auto_assign.py` — rank candidates using duty dates and range coverage; expose replacement selection without writing rows.
- Modify: `backend/app/services/weapon_eligibility.py` — consume the shared coverage seam so future-duty eligibility has the same primary/reserve/excusal semantics.
- Modify: `backend/app/services/ranges.py` — invoke reconciliation after creating assignments and provide an internal non-notifying removal/refill transaction seam.
- Modify: `backend/app/services/range_excusal.py` — reconcile later rosters after pending primary excusal requests and approved primary excusals.
- Modify: `backend/app/db/models.py` only if a persisted shortage/reconciliation audit field is required; prefer existing audit logs and roster notifications unless tests prove persistence is needed.
- Modify: `backend/tests/unit/test_range_candidates.py` — candidate ranking and coverage matrix.
- Modify: `backend/tests/unit/test_range_excusal.py` or the existing excusal unit test file — excusal-dependent coverage and refill behavior.
- Modify: `backend/tests/unit/test_ranges_service.py` — assignment-triggered reconciliation, slot preservation, and shortage behavior.
- Modify: `backend/tests/unit/test_eligibility.py` — shared weapon-duty projection regressions.
- Modify: `backend/tests/integration/test_ranges_api.py` — end-to-end batch/single assignment and roster response behavior.
- Modify: `frontend/src/api/ranges.ts` only if the API exposes a new reconciliation/shortage field; otherwise no frontend contract change.
- Modify: `frontend/src/pages/RangesPage.tsx` only if existing roster invalidation does not refresh automatically after reconciliation.
- Create or modify: `docs/superpowers/specs/2026-08-29-range-candidate-sequencing.md` — record the approved behavioral contract if the project requires a durable spec separate from this plan.

### Task 1: Lock the coverage truth table in tests

**Files:**
- Test: `backend/tests/unit/test_range_candidates.py`
- Test: `backend/tests/unit/test_eligibility.py`

**Interfaces:**
- Consumes the existing `RangeAssignment`, `RangeExcusalRequest`, `RangeEvent`, `DutyAssignment`, and qualification fixtures.
- Produces executable examples for the shared coverage seam and candidate-ranking contract.

- [ ] **Step 1: Add failing candidate tests for date ordering.** Cover: an earlier primary range qualifies a later weapon duty; a later primary range does not qualify an earlier duty; an earlier range does not cause the soldier to be excluded from the current event merely because they have another range later.
- [ ] **Step 2: Add failing tests for assignment kind.** Cover: primary range outranks reserve range; reserve range is not qualification until confirmed/called up; pending primary excusal is reserve-like; draft primary and draft reserve do not count.
- [ ] **Step 3: Add failing tests for upcoming-duty ranking.** Verify primary duties are ranked before reserve duties, only duties after the candidate range date are considered for “needs this range,” and the earliest date wins within each kind.
- [ ] **Step 4: Run focused tests and confirm the new cases fail for the current implementation.**

Run from `backend/`:

```powershell
pytest -q tests/unit/test_range_candidates.py tests/unit/test_eligibility.py
```

Expected: existing tests pass; the newly added sequencing cases fail.

- [ ] **Step 5: Commit the failing tests.**

```powershell
git add backend/tests/unit/test_range_candidates.py backend/tests/unit/test_eligibility.py
git commit -m "test(ranges): specify date-aware primary and reserve coverage"
```

### Task 2: Implement the shared coverage seam

**Files:**
- Create: `backend/app/services/range_coverage.py`
- Modify: `backend/app/services/ranges.py` if validity-day lookup needs a cycle-safe shared helper.
- Test: `backend/tests/unit/test_range_candidates.py` and `backend/tests/unit/test_eligibility.py`

**Interfaces:**
- Produce `RangeCoverage` with at least `qualified: bool`, `coverage_kind: Literal["qualification", "primary_range", "reserve_range", "none"]`, `source_event_date: date | None`, and `valid_until: date | None`.
- Produce `get_range_coverage(session, *, soldier_id, required_range_type, as_of) -> RangeCoverage`.
- Produce a bulk equivalent for candidate lists so ranking remains a bounded number of queries.

- [ ] **Step 1: Extract the shared range-type hierarchy and validity calculation without changing behavior.** Keep `RANGE_TYPE_RANK` semantics and existing configurable validity days.
- [ ] **Step 2: Implement current qualification lookup.** Existing qualification rows count when `valid_until >= as_of`; source attendance remains governed by the existing qualification-record behavior.
- [ ] **Step 3: Implement future assignment lookup.** Only non-draft planned primary assignments at or before `as_of` may provide future qualification. Exclude assignments with pending excusal requests. Treat reserve assignments as reserve coverage only when the existing attendance/call-up state says they are confirmed; otherwise return no qualification.
- [ ] **Step 4: Make the helper select the earliest applicable qualifying source and return its effective validity window.** Never let an assignment after `as_of` satisfy `as_of`.
- [ ] **Step 5: Run the focused tests and make the Task 1 cases pass.**
- [ ] **Step 6: Commit the shared seam.**

```powershell
git add backend/app/services/range_coverage.py backend/app/services/ranges.py backend/tests/unit/test_range_candidates.py backend/tests/unit/test_eligibility.py
git commit -m "feat(ranges): add shared date-aware coverage classification"
```

### Task 3: Update candidate ranking and explanations

**Files:**
- Modify: `backend/app/services/range_auto_assign.py`
- Test: `backend/tests/unit/test_range_candidates.py`
- Optionally modify: `frontend/src/api/ranges.ts` and `frontend/src/i18n/he.json` only if new reason codes are exposed.

**Interfaces:**
- Keep `rank_candidates_with_excluded(...)` and `RankedCandidate` compatible with the existing route/UI.
- Add internal bulk lookup keyed by `(soldier_id, event.date, required_range_type)`; do not reintroduce per-soldier query loops.

- [ ] **Step 1: Add failing tests for candidate explanations.** Verify explanations identify valid qualification, primary upcoming duty, reserve upcoming duty, and no qualification using the correct dates; pending-excusal range coverage must not be described as guaranteed qualification.
- [ ] **Step 2: Replace the current “future duty from today” ranking input with future duties relative to `event.date`.** Only published weapon duties with `start_date > event.date` are candidates for range-priority ranking; retain primary-before-reserve ordering and earliest date within each kind.
- [ ] **Step 3: Use the shared coverage seam for the qualified tier.** A qualification or earlier valid primary range may place a soldier in the qualified tier; a reserve-like source cannot do so.
- [ ] **Step 4: Preserve all existing hard exclusions and warning behavior.** Do not change same-day range exclusion, scope, exemptions, structural eligibility, or constraint overrides.
- [ ] **Step 5: Run the complete focused candidate file and confirm both old and new tests pass.**
- [ ] **Step 6: Commit.**

```powershell
git add backend/app/services/range_auto_assign.py backend/tests/unit/test_range_candidates.py frontend/src/api/ranges.ts frontend/src/i18n/he.json
git commit -m "feat(ranges): rank candidates by date-aware coverage"
```

### Task 4: Align weapon-duty eligibility with candidate semantics

**Files:**
- Modify: `backend/app/services/weapon_eligibility.py`
- Test: `backend/tests/unit/test_eligibility.py`
- Test: `backend/tests/integration/test_calendar_api.py` if projected calendar badges are affected.

**Interfaces:**
- Existing eligibility callers continue to receive the same `DutyEligibilityFact` shape unless a new explanatory field is needed.
- `future_windows` must be generated from the shared coverage rules or a directly shared query helper.

- [ ] **Step 1: Add failing regressions for primary, reserve, pending-excusal, and draft future ranges at a specified duty date.**
- [ ] **Step 2: Replace duplicated future-window filtering with the shared seam or make the shared seam the single source for the classification predicates.**
- [ ] **Step 3: Preserve the existing `future_start` and pending-excusal setting behavior where it is intentionally configurable; document the distinction between “eligibility projection” and “candidate ranking.”**
- [ ] **Step 4: Run the focused eligibility and calendar tests.**
- [ ] **Step 5: Commit.**

```powershell
git add backend/app/services/weapon_eligibility.py backend/tests/unit/test_eligibility.py backend/tests/integration/test_calendar_api.py
git commit -m "fix(eligibility): share primary and reserve range coverage rules"
```

### Task 5: Add transactional later-roster reconciliation and refill

**Files:**
- Create: `backend/app/services/range_reconciliation.py`
- Modify: `backend/app/services/ranges.py`
- Modify: `backend/app/services/range_excusal.py`
- Test: `backend/tests/unit/test_ranges_service.py`
- Test: `backend/tests/unit/test_range_excusal.py`

**Interfaces:**
- Produce `reconcile_future_range_assignments(session, *, soldier_id, source_event, actor_id) -> ReconciliationResult`.
- `ReconciliationResult` records removed assignment IDs, refilled primary/reserve assignment IDs, and unfilled slot kinds/counts.
- Reconciliation must use an internal assignment constructor that does not commit midway, then commit once with the triggering operation.

- [ ] **Step 1: Add failing tests for the replacement matrix.** Cover:
  - earlier non-excused primary range removes the same soldier from a later primary assignment;
  - earlier range removes a later reserve assignment as well;
  - earlier reserve assignment does not remove a later assignment until called up/confirmed;
  - pending excusal on the earlier primary makes it reserve-like and does not remove the later primary coverage;
  - drafts are neither removed nor used as triggers;
  - a later range before the relevant duty is removed when the earlier range already covers that duty.
- [ ] **Step 2: Add failing tests for slot-preserving refill.** A removed primary is refilled only in the later event’s primary slot; a removed reserve is refilled only in its reserve slot. The replacement cannot already be assigned to that later event or another range on that date.
- [ ] **Step 3: Add a failing shortage test.** When no candidate exists, the later slot stays empty, the result records the shortage, and the operation does not roll back the valid removal.
- [ ] **Step 4: Implement deterministic target discovery.** Query only future planned events for the soldier, order by event date, ignore the source event, cancelled/completed events, and drafts. Determine redundancy against duties after each target event using the shared coverage rules.
- [ ] **Step 5: Implement internal removal with audit and roster-notification collection.** Reuse the existing reason/audit shape, but avoid calling the public remove function because it commits and requires a separate request lifecycle.
- [ ] **Step 6: Implement refill using the ranked candidate list and `_validate_and_build_assignment`.** Select the first eligible candidate for the exact missing slot kind; add the row, reason code, audit/notification data, and capacity-safe result in the same transaction.
- [ ] **Step 7: Invoke reconciliation after single and batch assignment creation, only for non-draft assignments.** Reconciliation must run after the new source assignment is flushed, before the outer commit/notification pass.
- [ ] **Step 8: Invoke reconciliation when a primary excusal request is created, because pending excusal changes guaranteed coverage, and after an approved primary excusal.** Reserve excusal remains immediate deletion and should trigger only the existing affected-soldier eligibility recheck unless it creates a separate approved coverage transition.
- [ ] **Step 9: Run focused service and excusal tests.**
- [ ] **Step 10: Commit.**

```powershell
git add backend/app/services/range_reconciliation.py backend/app/services/ranges.py backend/app/services/range_excusal.py backend/tests/unit/test_ranges_service.py backend/tests/unit/test_range_excusal.py
git commit -m "feat(ranges): reconcile duplicate future assignments and refill slots"
```

### Task 6: Verify API/UI behavior and regression safety

**Files:**
- Test: `backend/tests/integration/test_ranges_api.py`
- Test: `frontend/src/pages/RangesPage.test.tsx` if roster invalidation or displayed explanations change.
- Modify: `frontend/src/api/ranges.ts`, `frontend/src/pages/RangesPage.tsx`, or `frontend/src/i18n/he.json` only when the integration tests identify a required contract change.

**Interfaces:**
- Existing `GET /ranges/{event_id}/candidates` and batch assignment response remain backward compatible.
- Existing roster-change notifications/query invalidation refresh both the source and affected future events.

- [ ] **Step 1: Add failing integration tests for single and batch assignment.** Verify the response succeeds, the source assignment is present, later duplicate assignments are removed, replacements preserve slot kind, and shortages are visible through the existing event data or a documented response field.
- [ ] **Step 2: Add a stale-candidate race test.** If a candidate becomes assigned elsewhere between candidate retrieval and batch save, the save must preserve existing validation and report the real failure without partial writes.
- [ ] **Step 3: Confirm frontend candidate rendering remains valid.** If no new fields are needed, explicitly test that existing explanations and roster refresh continue to work. If shortages need a visible field, add the smallest typed field and Hebrew copy.
- [ ] **Step 4: Run focused backend integration tests and frontend tests.**

```powershell
pytest -q tests/unit/test_range_candidates.py tests/unit/test_ranges_service.py tests/unit/test_range_excusal.py tests/unit/test_eligibility.py tests/integration/test_ranges_api.py
cd ..\frontend
npx vitest run src/pages/RangesPage.test.tsx
npm run typecheck
```

- [ ] **Step 5: Run the stable broader checks from the repository instructions.** Backend from `backend/`; frontend from `frontend/`; use serial Vitest if cross-file parallelism is flaky.
- [ ] **Step 6: Commit any narrow API/UI corrections.**

### Task 7: Documentation and completion review

**Files:**
- Create or modify: `docs/superpowers/specs/2026-08-29-range-candidate-sequencing.md`
- Modify: `frontend/CHANGELOG.md` only during the project’s normal `dev` -> `master` release, not in this feature branch.

- [ ] **Step 1: Record the final truth table and explicit definitions of primary, reserve, pending excusal, approved excusal, called-up, confirmed attendance, planned, and draft.**
- [ ] **Step 2: Review the diff for duplicate authority paths.** Candidate ranking, weapon eligibility, and reconciliation must all use the shared coverage semantics.
- [ ] **Step 3: Confirm no automatic behavior touches completed/cancelled events or drafts and no primary/reserve counts are merged.
- [ ] **Step 4: Run the required verification before claiming completion and report any unrun full-suite checks separately.**

## Self-Review Checklist

- Primary before duty: qualifies only if not pending excusal.
- Primary after duty: does not qualify that duty.
- Reserve before duty: does not qualify until called up/confirmed.
- Later duplicate range: removed only when earlier guaranteed coverage exists.
- Replacement: same event, same slot kind, normal candidate eligibility, one transaction.
- No replacement: shortage retained and reported.
- Existing hard exclusions and authorization: unchanged.
- Drafts: never counted, removed, or used for automatic refill.
