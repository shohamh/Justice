# Swaps, Ranges, Hierarchy Transfers & Rank Advancement E2E Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the real-stack Playwright suite in `frontend/tests/e2e/smoke` with four new journeys — duty swaps, range scheduling/attendance/qualification, hierarchy transfer requests, and rank-advancement interval configuration — closing the largest remaining gaps identified against `docs/e2e-coverage-matrix.md`.

**Architecture:** Same pattern as `frontend/tests/e2e/smoke/multi_user_duty_problems.spec.ts`: real FastAPI + PostgreSQL backend, role-based browser contexts from `tests/e2e/fixtures/auth.ts`, every mutation driven through visible UI controls and confirmed via `page.waitForResponse` on the real API call, cross-role state re-read after refresh rather than trusting HTTP status alone.

**Tech Stack:** Playwright Test, Chromium, FastAPI, PostgreSQL, Alembic, TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-01-browser-automation-strategy.md`

## Global Constraints

- Test Chrome desktop only for these four journeys (per spec: mobile is required for the *original* 10 blocking journeys; these are `@full`-tier additions, desktop-only is acceptable — see Task 5 of the original plan's tiering).
- Use the real frontend, backend, and PostgreSQL stack. Never use `page.request`/direct DB writes to perform the mutation under test — only to *read* already-authenticated state when a UI selector is otherwise ambiguous (see Task 1's swap-claim resolution and the precedent in `multi_user_duty_problems.spec.ts`'s `grantHakpazaPikudit`).
- Do not enable video by default; keep trace/screenshot-on-failure.
- Preserve Hebrew/RTL behavior; assert user-visible translated states (e.g. status badge text, not just internal enum values).
- Do not weaken backend authorization to make setup easier.
- **Verify every new spec against a freshly reseeded database** (`backend/app/scripts/seed.py --db-url <e2e db> --clear`) run at least twice in a row before considering a task done. Local repeated runs against a non-reseeded DB accumulate future-dated fixtures for the same seeded actors and produce `.first()`-selector flakiness that looks like a real bug but isn't (see `git log` on `feature/browser-automation-tests` — the `test: stabilize multi-user duty problem journey…` commit is a worked example of this class of bug).
- Where a UI-driven step turns out to target state that cannot actually be reached through the UI (e.g. a background-worker-only side effect), do not force it — scope the test to what a real user can do and say so in the spec's seam-inventory comment, matching the header comment block already in `multi_user_duty_problems.spec.ts`.

---

### Task 1: Swaps journey (`frontend/tests/e2e/smoke/swaps.spec.ts`)

**Files:**
- Create: `frontend/tests/e2e/smoke/swaps.spec.ts`
- Modify: `frontend/tests/e2e/fixtures/auth.ts` — add two journey actors: `swapRequester: "1000013"`, `swapCovering: "1000014"` (both plain soldiers, next free personal numbers after `1000012`)
- Modify: `backend/app/scripts/seed.py` — only if `1000013`/`1000014` collide with existing seed rows; otherwise no backend changes needed since new soldiers aren't required (any two `role: "soldier"` seed accounts eligible for the same duty type/hierarchy scope work — confirm via `GET /api/soldiers` during Step 1 before adding new fixtures)
- Modify: `docs/e2e-coverage-matrix.md` — add the new row

**Interfaces (from research — verified endpoints/testids, not guesses):**
- Create request: `AskSwapModal` → checkbox `ask-swap-marketplace-checkbox`, search input `ask-swap-target-search` → `POST /api/me/swaps`
- Marketplace claim/offer: `SwapsPage` board tab (`?tab=1`) → per-card button text `t("swaps.cover")` (no testid — select via `getByRole("button", { name: /לכסות|cover/ })` scoped to the specific card, or by row text matching the shift/location name created earlier in the test) → `CoverOfferModal` → radio group `cover_mode` (free/trade) → submit → `POST /api/swaps/{id}/offer`
- Soldier-side accept: `SwapsPage` incoming tab (`?tab=2`) → buttons with i18n text `approvals.approve` / `approvals.reject` (no testid) → `POST /api/me/swaps/{id}/approve` or `/reject`
- Manager approval: `SwapsPage` pending tab (`?tab=3`, role-gated to admin/duty_manager/commander) → `SwapApprovalColumns` approve/reject buttons (no testid, same i18n keys) → `POST /api/swaps/{id}/manager-approve` (body `{side: "requester"|"covering", candidate_id?}`) / `manager-reject`
- Final state: swap row badge color/text via `STATUS_COLORS`/`statusKey` on `MySwapCard` (`data-testid="swap-row-${id}"`)

- [ ] **Step 1: Confirm actor eligibility and add journey actors**

  Run against a running dev stack: `GET /api/soldiers` as admin and inspect personal numbers `1000013`/`1000014` are unused (seed creates 116 soldiers; confirm the exact ceiling by checking `backend/app/scripts/seed.py`'s soldier-creation loop, `pn_counter = 1000001` at line 259, and how many soldiers it increments through). If they collide, pick the next free pair instead and use that pair consistently below.

  Add to `frontend/tests/e2e/fixtures/auth.ts`:
  ```ts
  export const journeyActors = {
    assignedExemption: "1000009",
    assignedGimelim: "1000010",
    assignedAbsent: "1000011",
    assignedHakpaza: "1000012",
    firstReserve: "1000002",
    secondReserve: "1000003",
    swapRequester: "1000013",
    swapCovering: "1000014",
  } as const;
  ```
  (Keep `journeyActorStorageState`/`roleStorageState` machinery unchanged — it already generalizes over the `journeyActors` map.)

- [ ] **Step 2: Write the spec skeleton with a seam-inventory header comment**

  Model the file on `multi_user_duty_problems.spec.ts`'s structure: imports from `../fixtures/test` and `../fixtures/auth`, a top-of-file comment block listing every control/endpoint pair from the Interfaces section above (this is required by the existing pattern — it's what let us quickly diagnose the gimelim `ReserveError` bug during the last round of work), then helper functions per step, then `test.describe.configure({ mode: "serial" })`.

- [ ] **Step 3: Build a real duty to swap**

  Reuse `createAndPublishAlgorithmDuty`-style helper (copy and adapt from `multi_user_duty_problems.spec.ts`, or better, factor the shared shift-creation logic into `frontend/tests/e2e/support/data.ts` if it doesn't already exist there — check first) as `dutyManager`, then manually assign `swapRequester` (`1000013`) as primary via `assignManually`-style flow. Use a far-future date offset (`1500 + Math.floor(Math.random() * 100)` days out, matching the established convention) to avoid colliding with other suites' seeded/accumulated data.

- [ ] **Step 4: `swapRequester` creates and publishes a swap request**

  As `swapRequester`, navigate to `/swaps?tab=0`, open `AskSwapModal` from the duty row, check `ask-swap-marketplace-checkbox`, submit. Wait for `POST /api/me/swaps` to return 2xx and capture the created `request_id` from the response body for later assertions.

- [ ] **Step 5: `swapCovering` claims/offers on the marketplace**

  As `swapCovering`, navigate to `/swaps?tab=1` (board). Locate the card for the duty created in Step 3 (match by location/date text, not `.first()` — apply the lesson from the Hakpaza fix: if multiple cards could plausibly match due to DB accumulation across local runs, resolve the correct swap's id via an authenticated fetch of `GET /api/swaps/board` intercepted from the page's own request, the same pattern used for `/api/soldiers` in `multi_user_duty_problems.spec.ts`'s `grantHakpazaPikudit`). Open `CoverOfferModal`, select `cover_mode` "free", submit. Wait for `POST /api/swaps/{id}/offer` to return 2xx.

- [ ] **Step 6: `swapRequester` approves the covering offer**

  As `swapRequester`, navigate to `/swaps?tab=2` (incoming) or `?tab=0` depending on which side the approval surfaces on (verify by reading `SwapsPage.tsx`'s tab-routing logic for the requester-approve case — `soldierApproveSwap` — before writing the selector). Click the approve control, wait for `POST /api/me/swaps/{id}/approve` to return 2xx.

- [ ] **Step 7: Manager approves both sides and the swap finalizes**

  As `dutyManager` (or whichever role `GET /api/swaps/config` reports as required approver — read `require_manager_approval`/`require_duty_manager_approval` from that endpoint during setup rather than assuming), navigate to `/swaps?tab=3`, find the pending row, approve requester side then covering side via `SwapApprovalColumns`, waiting for `POST /api/swaps/{id}/manager-approve` after each click. After the second approval, assert the finalized status server-side effect is visible: refresh `/swaps?tab=0` as `swapRequester` and assert the row's status badge text reflects completion (not just that the API returned 2xx — this is the "assert visible post-mutation state" constraint from the spec).

- [ ] **Step 8: Cross-role visibility check**

  As `swapCovering`, navigate to `/my-duties` and assert the duty now appears in their upcoming list (the swap's real consequence — the assignment ownership actually moved).

- [ ] **Step 9: Run against a freshly seeded DB, twice**

  ```powershell
  cd backend
  .venv\Scripts\python.exe -m app.scripts.seed --db-url "postgresql+psycopg://app:app_pw@localhost:5432/justice_e2e" --clear
  cd ..\frontend
  Remove-Item -Recurse -Force .playwright\auth
  npx playwright test --grep swaps --project=desktop --retries=0
  ```
  Repeat the reseed+run twice. Both runs must pass with no retries.

- [ ] **Step 10: Update the coverage matrix and commit**

  Add a row to `docs/e2e-coverage-matrix.md`:
  `| Soldier, soldier, duty manager | Duty swap | Claimed swap finalizes and assignment ownership visibly transfers | Desktop | Full | \`smoke/swaps.spec.ts\` |`

  ```bash
  git add frontend/tests/e2e/smoke/swaps.spec.ts frontend/tests/e2e/fixtures/auth.ts docs/e2e-coverage-matrix.md
  git commit -m "test: cover duty swap marketplace and approval journey"
  ```

---

### Task 2: Ranges journey (`frontend/tests/e2e/smoke/ranges.spec.ts`)

**Files:**
- Create: `frontend/tests/e2e/smoke/ranges.spec.ts`
- Modify: `docs/e2e-coverage-matrix.md`

No new journey actors strictly required — the seeded past/upcoming `RangeEvent`s (seed.py ~line 1692-1730) already have soldiers assigned with attendance history, and the existing `dutyManager`/`admin`/`soldier` roles cover the needed permissions. Add one journey actor only if the seeded upcoming event's assigned soldiers don't map cleanly to an existing role fixture — check `backend/app/scripts/seed.py` lines 1692-1730 for which personal numbers are used there first.

**Interfaces (verified):**
- Page boundary: `data-testid="ranges-page"`, route `/ranges`. Feature gated by `mitvachim.enabled` (already forced on in seed — no admin toggle step needed, unlike Hakpaza).
- Create event: `create-event-button` → `RangeFormModal` form `create-event-form`, sections `range-form-section-schedule/contact/notes`, footer `range-form-footer`
- Assign soldiers: per-row `view-assignments-{eventId}` → `RangeEditAssignmentsModal`, candidate checkboxes `primary-candidate-{soldierId}`/`reserve-candidate-{soldierId}` (confirm exact prefix by reading `RangeEditAssignmentsModal.tsx:524` before writing selectors — the agent reported "likely" prefix, verify it), auto-select buttons `range-auto-select-primary`/`range-auto-select-reserve`, save `save-assignments`
- Attendance: `RangeDetailContent` roster `range-detail-roster`, search `range-roster-search`, per-assignment `present-{assignmentId}` / `no-show-{assignmentId}` (in `RangeAttendanceStatusPicker.tsx`), note `note-{assignmentId}`, save `attendance-save-button` → `PATCH /api/ranges/{event_id}/assignments/{assignment_id}/attendance`
- Excusal: self-service `range-self-excusal-action` → `submit-excuse-button` → `POST /api/ranges/{event_id}/assignments/{assignment_id}/excuse`; DM review `excusal-review-queue` → `approve-excusal-{requestId}`/`reject-excusal-{requestId}` → `POST /api/ranges/{event_id}/excusal-requests/{request_id}/decide`
- Qualification: `qualification` tab → `IneligibleSoldiersTable` (`ineligible-soldiers-view`), warning badges `ineligible-warning-{soldier_id}`

- [ ] **Step 1: Verify exact candidate-checkbox testid prefix**

  Read `frontend/src/components/RangeEditAssignmentsModal.tsx` around line 524 (or wherever the checkbox renders in the current file — line numbers may have shifted) and confirm the literal `data-testid` template string before writing any selector against it.

- [ ] **Step 2: Write the spec skeleton with seam-inventory header**

  Same convention as Task 1 — list every control/endpoint pair used, matching `multi_user_duty_problems.spec.ts`'s style.

- [ ] **Step 3: `dutyManager` creates a range event and assigns soldiers**

  Navigate to `/ranges`, click `create-event-button`, fill `RangeFormModal` (date far-future per the offset convention, location from the 3 seeded `RangeLocation`s), submit, wait for `POST /api/ranges` 2xx and capture `event_id`. Open `view-assignments-{event_id}`, assign one primary and one reserve (use the seeded `assignedExemption`/`assignedGimelim` actors or any two soldiers confirmed free of conflicting future duties — check via the same accumulation caution as Task 1), save, wait for the batch-assign response.

- [ ] **Step 4: Mark attendance on the seeded past event**

  Navigate to the seeded past laser-range event (locate it via `GET /ranges?node_id=` matching the seed's root node, or by date filter — do not use `.first()` if more than one past event could exist after repeated local runs; the seed only creates one past event per `--clear` reseed, so this is safe against a freshly reseeded DB but not against accumulated state — note this explicitly in the spec comment). Mark one assignment present, one no-show with a note, save, wait for the attendance `PATCH` 2xx. Refresh and assert the status badges persisted.

- [ ] **Step 5: Excusal request + DM decision on the newly created event**

  As the soldier assigned in Step 3, navigate to their duty/range view, submit an excusal (`submit-excuse-button`) with a reason, wait for `POST .../excuse` 2xx. As `dutyManager`, navigate to `excusal-review-queue` for that event, approve it (`approve-excusal-{id}`), wait for the `decide` endpoint 2xx. Refresh the soldier's view and assert the excusal shows approved.

- [ ] **Step 6: Qualification/eligibility view**

  As `dutyManager` or `admin`, open the `qualification` tab, assert `ineligible-soldiers-view` renders and that a soldier with no qualification record (or an expired one, from the seeded past event's no-show) shows an `ineligible-warning-{soldier_id}` badge.

- [ ] **Step 7: Run against a freshly seeded DB, twice** (same reseed+run procedure as Task 1, `--grep ranges`)

- [ ] **Step 8: Update coverage matrix and commit**

  ```bash
  git add frontend/tests/e2e/smoke/ranges.spec.ts docs/e2e-coverage-matrix.md
  git commit -m "test: cover range scheduling, attendance, and excusal journey"
  ```

---

### Task 3: Hierarchy transfer request journey (`frontend/tests/e2e/smoke/hierarchy_transfers.spec.ts`)

**Files:**
- Create: `frontend/tests/e2e/smoke/hierarchy_transfers.spec.ts`
- Modify: `frontend/tests/e2e/fixtures/auth.ts` — add one journey actor if needed: `transferSoldier` (a soldier eligible to move between two hierarchy nodes the seed already creates — confirm two sibling/parent nodes with distinct commanders exist in seed's 19 hierarchy nodes before picking source/destination)
- Modify: `docs/e2e-coverage-matrix.md`

**Interfaces (verified):**
- Create: `HierarchyTree.tsx` (or `UnifiedSoldierModal.tsx`/`EntriesExitsPanel.tsx`) form field `transfer-reason` → `POST /api/hierarchy-transfers`
- Requester view: `MyRequestsPage` "transfers" tab
- Approver view: `ApprovalsPage`, tab `approvals-tab-transfers` → `onTransferApprove`/`onTransferReject` handlers → `POST /api/hierarchy-transfers/{id}/approve` / `/reject`

- [ ] **Step 1: Identify two hierarchy nodes with distinct approvers**

  Read `backend/app/scripts/seed.py`'s hierarchy-node creation block and pick a source node (holding a soldier we can move) and a destination node with a commander/duty-manager distinct from the source's, so the approval step exercises real cross-scope authorization rather than a same-person edge case. Record the node names/ids needed for the UI navigation.

- [ ] **Step 2: Write the spec skeleton with seam-inventory header** (same convention)

- [ ] **Step 3: Create the transfer request**

  As `commander` (or whichever role `HierarchyTree.tsx`'s create entry point authorizes — confirm by reading the component's guard before assuming `commander` is correct), navigate to `/team`, open the tree, select the soldier to move, fill `transfer-reason`, submit. Wait for `POST /api/hierarchy-transfers` 2xx and capture the request id.

- [ ] **Step 4: Requester-side visibility**

  As the same commander (or the soldier, per whatever the actual requester role turns out to be from Step 3), navigate to `/my-requests`, select the transfers tab, assert the new request appears pending.

- [ ] **Step 5: Destination approver decides**

  As the destination node's commander/duty-manager, navigate to `/approvals`, select `approvals-tab-transfers`, locate the row, click approve. Wait for `POST /api/hierarchy-transfers/{id}/approve` 2xx.

- [ ] **Step 6: Cross-role visibility check**

  Refresh `/team` as an admin or the destination commander and assert the soldier now appears under the destination node (the transfer's real consequence, not just a 2xx).

- [ ] **Step 7: Rejection path (second test in the same spec)**

  Repeat Steps 3-4 with a fresh soldier/date, then have the destination approver reject with a required reason via `onTransferReject`, and assert the requester sees the rejection reason in `/my-requests`.

- [ ] **Step 8: Run against a freshly seeded DB, twice** (`--grep hierarchy_transfers`)

- [ ] **Step 9: Update coverage matrix and commit**

  ```bash
  git add frontend/tests/e2e/smoke/hierarchy_transfers.spec.ts frontend/tests/e2e/fixtures/auth.ts docs/e2e-coverage-matrix.md
  git commit -m "test: cover hierarchy transfer request approve/reject journey"
  ```

---

### Task 4: Rank advancement interval configuration (`frontend/tests/e2e/smoke/rank_advancement_config.spec.ts`)

**Scope note:** Actual rank promotion only happens via the daily `run_rank_advancement_worker()` background job (`backend/app/rank_advancement_worker.py`) — there is no UI control that triggers a promotion, so promotion itself is explicitly **out of scope** for browser E2E (per the Global Constraints rule on not forcing untestable UI state). This task covers the one real user-facing surface: the admin interval editor, whose side effect (recomputing `next_rank_date` for affected soldiers) *is* observable and worth asserting.

**Files:**
- Create: `frontend/tests/e2e/smoke/rank_advancement_config.spec.ts`
- Modify: `docs/e2e-coverage-matrix.md`

**Interfaces (verified):**
- Page: `SystemSettingsPage.tsx`, `RankAdvancementIntervalsSection` (select the "עליית דרגה" settings group first)
- Inputs: months input and career-entry checkbox keyed by `draftKey(track, rank)` — **no `data-testid` exists on these inputs yet**; this task must add one before it can select reliably (see Step 1)
- API: `GET /api/soldiers/rank-ladder`, `PUT /api/soldiers/rank-advancement-intervals` (admin-only)

- [ ] **Step 1: Add `data-testid` to the interval inputs**

  Read `frontend/src/pages/SystemSettingsPage.tsx` around `RankAdvancementIntervalsSection` (line ~675-820) and add `data-testid={\`rank-interval-months-${track}-${rank}\`}` to the months input and `data-testid={\`rank-interval-career-entry-${track}-${rank}\`}` to the checkbox, using the existing `draftKey(track, rank)` values so the ids are stable and predictable. This is the one production-code change in this task — keep it minimal, matching the existing selector-naming convention used elsewhere in the file.

- [ ] **Step 2: Write the spec skeleton with seam-inventory header**

- [ ] **Step 3: Admin edits an interval and it persists**

  As `admin`, navigate to `/admin/settings`, select the rank-advancement settings group, change one track/rank's months value via the new testid, save. Wait for `PUT /api/soldiers/rank-advancement-intervals` 2xx. Reload the page and assert the changed value is still shown (persisted, not just accepted).

- [ ] **Step 4: Assert the recompute side effect on an affected soldier**

  Pick a soldier on the edited track/rank (from seed data — identify one via `GET /api/soldiers` filtered by rank, same authenticated-fetch pattern as the swap-board resolution in Task 1 to avoid a `.first()`-style mismatch). Navigate to their profile as admin, assert the displayed "next rank date" reflects the new interval (read the exact field/testid from `ProfilePage.tsx` before writing the assertion — the research pass only confirmed rank is *shown*, not the exact next-rank-date selector, so verify this during implementation).

- [ ] **Step 5: Run against a freshly seeded DB, twice** (`--grep rank_advancement_config`)

- [ ] **Step 6: Update coverage matrix and commit**

  Add a row noting promotion itself is worker-only and explicitly out of scope, so a future reader doesn't assume this spec covers actual promotions.

  ```bash
  git add frontend/tests/e2e/smoke/rank_advancement_config.spec.ts frontend/src/pages/SystemSettingsPage.tsx docs/e2e-coverage-matrix.md
  git commit -m "test: cover rank advancement interval configuration and recompute"
  ```

---

## Verification commands

Run from `frontend` unless noted, against a freshly reseeded E2E database (see Global Constraints):

```powershell
npx playwright test --grep "swaps|ranges|hierarchy_transfers|rank_advancement_config" --project=desktop --retries=0
```

Run each spec individually at least twice from a clean reseed before considering its task done. Before claiming any task complete, verify: fresh-database repeatability (2x), no reliance on `.first()` where DB accumulation could make it ambiguous, failure artifacts are produced on an intentionally-broken run, and the coverage matrix row is accurate. Treat timeouts or interrupted commands as unverified.
