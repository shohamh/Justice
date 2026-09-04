# Swaps, Ranges, Hierarchy Transfers & Rank Advancement E2E Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the real-stack Playwright suite in `frontend/tests/e2e/smoke` with four new journeys — duty swaps (marketplace, shift-modal, proactive offer, free/trade cover, notifications, dual-role approval), range scheduling/attendance/qualification, hierarchy transfer requests (click-based and drag-and-drop), and rank advancement (manual rank/next-rank-date editing, interval configuration, and an actually-triggered promotion) — closing the largest remaining gaps identified against `docs/e2e-coverage-matrix.md`.

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

**Scope:** the user asked for multiple distinct swap sub-journeys, not one happy path. Six real, distinct code paths exist and must each get their own `test()` block in one spec file (serial, sharing setup helpers): marketplace claim, shift-modal claim, proactive "offer to replace," free cover, trade-with-another-duty cover, and notification click-through — plus approval exercised from **both** a commander and a duty_manager independently (confirmed in research: these are two independent `(side, approver_kind)` rows, not a chain — a commander approving one side does not require a duty_manager to go first).

**CORRECTED (was wrong in an earlier draft — verified against source directly):** `POST /swaps/take-free` **does** have a UI call site: `OfferSwapModal.tsx` (not `CoverOfferModal.tsx` — a separate component), reached from `ShiftDetailPanel`'s `swaps.offer_replace` button when viewing **another soldier's** duty that has no existing open swap on it yet. `OfferSwapModal` has its own `mode: "swap" | "free"` toggle:
- `mode: "free"` → `takeDutyFree(targetAssignmentId)` → `POST /swaps/take-free`. Server-side (`backend/app/services/swaps.py::take_free`), this creates a `SwapRequest` with `requesting_soldier_id = ` the **original duty owner** (not the acting/covering soldier) and a `SwapCandidate` for the acting soldier already `status="accepted"`. A `swap_offer` notification fires to the original owner ("another soldier wants to take your duty — approval required"). So taking-free is **not** instant — it still needs the original owner's soldier-side approval, then manager approval, same pipeline as any other swap. This is the "take for free" scenario.
- `mode: "swap"` → `createSwap({duty_assignment_id: <acting soldier's own duty>, target_soldier_id: <the duty owner being viewed>, reason})` → `POST /me/swaps`. Verified in `create_request` (`backend/app/services/swaps.py:90-119`): `requesting_soldier_id` must own `duty_assignment_id` (enforced via `_effective_soldier_on_date(...) == requesting_soldier_id`), so this is the **acting** soldier proactively offering **their own** duty to a specific target soldier — not a request created "on behalf of" the target, and not an automatic two-duty trade (the target's own duty doesn't move unless they separately publish it too). This is the "offer" scenario: a soldier proactively offering their own duty, from the shift-modal context, to a specific person.

The genuine two-duty trade mechanic is `CoverOfferModal`'s trade mode (below): a soldier claiming someone else's **already-open** ask can add one of their own duties into the offer, so two duties actually change hands. That satisfies "swap with another duty."

**Files:**
- Create: `frontend/tests/e2e/smoke/swaps.spec.ts`
- Modify: `frontend/tests/e2e/fixtures/auth.ts` — add four journey actors, next free personal numbers after `1000012`: `swapRequesterA: "1000013"`, `swapCoveringA: "1000014"`, `swapRequesterB: "1000015"`, `swapCoveringB: "1000016"` (two independent requester/covering pairs so the marketplace test and the shift-modal test don't fight over the same duty/notification state)
- Modify: `docs/e2e-coverage-matrix.md`

**Interfaces (verified endpoints/testids/text — not guesses):**
- Entry point A — marketplace: `SwapsPage` "mine" tab (`swaps.ask_swap` button, no testid, text-select) → `AskSwapModal` → checkbox `ask-swap-marketplace-checkbox` → `POST /api/me/swaps`. Claim from `SwapsPage` board tab (`?tab=1`, `swaps.cover` button, text-select scoped to the card) → `CoverOfferModal`.
- Entry point B — shift modal: `/unit-calendar` → open a shift → `ShiftDetailPanel` → an *existing* open swap on that shift shows a `swaps.cover` button (text-select) → same `CoverOfferModal`. This is the identical modal as entry point A, reached from a different page — the test proves both navigation paths converge on the same working flow.
- Entry point C — proactive offer/take: `ShiftDetailPanel` → `swaps.offer_replace` button (text-select, shown when viewing another soldier's duty with no open swap yet) → `OfferSwapModal.tsx` (mode toggle `"swap" | "free"`, no testids on the toggle — select by role+label text). `mode="free"` → `takeDutyFree()` → `POST /swaps/take-free` (original owner must soldier-approve, then manager-approve — see the corrected note above). `mode="swap"` → `createSwap()` with the acting soldier's own duty + the viewed soldier as `target_soldier_id` → `POST /me/swaps` (the target soldier must soldier-approve, then manager-approve). Read `ShiftDetailPanel.tsx`'s `offerSwapTarget` state (~line 356-362, 470-476, 556-560) and `OfferSwapModal.tsx` in full for exact field selectors before writing the test.
- `CoverOfferModal` (`frontend/src/components/CoverOfferModal.tsx`): radio group `name="cover_mode"`, no testids — select by role+label text `t("swaps.cover_free")` (free) vs `t("swaps.offer_trade")` (trade). Trade mode reveals a checkbox list of the covering soldier's own duties (`swaps.select_duties_to_offer`, plain checkboxes, no testid — select the first `input[type=checkbox]` in that list, or by matching the duty date/location text created for that actor). Submit → `POST /api/swaps/{id}/offer`.
- Soldier-side accept (both requester-approves-cover and candidate-approves-invite use the same pair): buttons with text `approvals.approve` / `approvals.reject` on `SwapsPage` incoming/mine cards → `POST /api/me/swaps/{id}/approve` / `/reject`.
- Manager approval: `SwapsPage` pending tab (`?tab=3`) → `PendingApprovalCard` → `SwapApprovalColumns` approve/reject buttons (text-select, same i18n keys) → `POST /api/swaps/{id}/manager-approve` (body `{side, candidate_id?}`) / `manager-reject`. **Test both approver kinds separately**: log in as `commander`, approve the requester side of swap A; log in as `dutyManager`, approve the covering side of the *same* swap A — confirm both succeed independently and the swap only finalizes once both required `(side, kind)` rows exist (read `_try_finalize`'s exact requirement — whether duty-manager approval is required in addition to commander depends on the `require_duty_manager_approval` setting from `GET /api/swaps/config`, fetch it during setup rather than assuming).
- Notifications: bell `data-testid="notification-bell"`, dropdown `data-testid="notification-dropdown"`, items are untested plain `<div>`s with no testid — select by containing text (the swap's duty/location name) inside the dropdown. Confirmed notification-firing points: `swap_offer` fires when `swapCoveringA` offers on A's request (assert this notification appears in `swapRequesterA`'s bell/dropdown); `swap_accepted`/`swap_rejected` fire on finalization (assert on both winner and any losing candidate if the test creates more than one candidate — optional, only if time allows). Click a notification and assert it navigates via `getNotificationLink` (e.g. a `swap_offer_incoming` notification routes to `/swaps?tab=incoming`) — this is the "clickable" requirement; assert the URL actually changes and the swap row is visible on the destination tab, not just that the click didn't error.

- [ ] **Step 1: Add journey actors and confirm they're free**

  Confirm `1000013`-`1000016` are unused the same way as before (check seed's soldier-creation ceiling), then add all four to `journeyActors` in `frontend/tests/e2e/fixtures/auth.ts`.

- [ ] **Step 2: Write the spec skeleton with a seam-inventory header comment**

  List every entry point (A/B/C above), every modal, every endpoint, and explicitly the "take-free has no UI" note, matching the header-comment convention in `multi_user_duty_problems.spec.ts`.

- [ ] **Step 3: Shared setup helper — two real duties to swap**

  One helper creates and manually assigns two separate future duties (far-future date offset, established convention), one primary'd to `swapRequesterA`, one to `swapRequesterB`, as `dutyManager`.

- [ ] **Step 4: Test — marketplace claim, free cover, dual-role approval, notification click-through**

  `swapRequesterA` creates+publishes via entry point A. `swapCoveringA` claims via the board tab with `cover_mode` free. Assert `swapRequesterA` sees a `swap_offer` notification in the bell (`notification-bell` shows a nonzero count, open `notification-dropdown`, assert the item text matches, click it, assert navigation to `/swaps?tab=incoming` and the row visible there). `swapRequesterA` approves. `commander` approves one side via `/swaps?tab=3`; `dutyManager` approves the other side. Assert the swap's status badge reads finalized for `swapRequesterA` and that `/my-duties` for `swapCoveringA` now shows the duty (assignment ownership actually moved).

- [ ] **Step 5: Test — shift-modal claim + trade-with-another-duty**

  `swapRequesterB` creates+publishes (entry point A is fine for creation; the point under test here is the *claim* path). `swapCoveringB` navigates to `/unit-calendar`, opens the shift via `ShiftDetailPanel`, claims through the `swaps.cover` button found there (entry point B), selects `cover_mode` trade, picks one of their own duties to offer, submits. Approve through both roles as in Step 4 (reusing the helper built there). Assert both sides' assignment ownership swapped correctly — this is the one scenario where *two* duties change hands, so assert both `/my-duties` views.

- [ ] **Step 6: Test — take for free (entry point C, `mode="free"`)**

  Assign a fresh duty to a third actor (e.g. `assignedExemption`, on a new far-future date). As `swapCoveringA` (or a fresh actor if A/B are busy with Steps 4-5), navigate to `/unit-calendar`, open that soldier's duty, click `swaps.offer_replace`, select `mode="free"`, submit. Wait for `POST /api/swaps/take-free` 2xx. As the original owner (`assignedExemption`), navigate to `/swaps`, approve (soldier-side). As `commander`/`dutyManager` (whichever `GET /api/swaps/config` requires), approve. Assert the duty now appears in the taker's `/my-duties`.

- [ ] **Step 7: Test — proactive offer (entry point C, `mode="swap"`)**

  Assign a fresh duty to a fourth actor (e.g. `assignedGimelim`, another existing journey-actor fixture — no new personal numbers needed for Steps 6-7). As `swapRequesterB` (or another free actor not already occupied by Steps 4-5's own assertions), navigate to `/unit-calendar`, open that soldier's duty, click `swaps.offer_replace`, select `mode="swap"`, choose one of the acting soldier's own duties to offer, submit. Wait for `POST /api/me/swaps` 2xx. As the target soldier, approve. As the required manager role, approve. Assert the acting soldier's original duty now appears in the target's `/my-duties` (ownership moved as the acting soldier proposed).

- [ ] **Step 8: Run against a freshly seeded DB, twice**

  ```powershell
  cd backend
  .venv\Scripts\python.exe -m app.scripts.seed --db-url "postgresql+psycopg://app:app_pw@localhost:5432/justice_e2e" --clear
  cd ..\frontend
  Remove-Item -Recurse -Force .playwright\auth
  npx playwright test --grep swaps --project=desktop --retries=0
  ```
  Repeat twice. Both runs must pass with no retries.

- [ ] **Step 9: Update the coverage matrix and commit**

  Add a row to `docs/e2e-coverage-matrix.md` covering all six sub-journeys and noting `take-free` is intentionally out of scope (dead endpoint, no UI).

  ```bash
  git add frontend/tests/e2e/smoke/swaps.spec.ts frontend/tests/e2e/fixtures/auth.ts docs/e2e-coverage-matrix.md
  git commit -m "test: cover duty swap marketplace, shift-modal, offer, and dual-role approval journeys"
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

**Scope:** the user asked for drag-and-drop coverage in addition to the click-based flow. Confirmed via research: `HierarchyTree.tsx` already implements soldier drag using `@dnd-kit/core` (pointer-sensor based, **not** native HTML5 drag events) — dragging a soldier row onto a node calls the exact same `createTransferRequest` flow as the click-based "quick add," just via `handleDragEnd` instead of a click handler. So drag-and-drop is a second *interaction mechanism* onto identical backend behavior, not a separate feature — write it as an additional `test()` that proves the mechanism works, not a full re-test of the approval flow (that's already covered by the click-based test).

**Interfaces (verified):**
- Create (click-based): `HierarchyTree.tsx` → `transfer-reason` form field → `POST /api/hierarchy-transfers`
- Create (drag-and-drop): soldier row drag handle `data-testid="tree-soldier-${personal_number}"` (only rendered when `canEdit`) → drop onto a node row (target the node's name element, `data-testid="tree-name-${nodeId}"` per the drop-target pattern in `HierarchyTree.tsx` — confirm the exact drop-target testid by reading `DroppableNodeRow` around line 127-202 before writing the test) → `handleDragEnd` → same `openTransferConfirmation` → `ConfirmDialog`/`transfer-reason` form → `POST /api/hierarchy-transfers`. **Not** the node-drag-to-move feature (`moveNode`, `POST /hierarchy/nodes/{id}/move`) — that's a different, immediate, no-approval hierarchy edit and is out of scope for this task (it's a structural admin action, not a "transfer request").
- Drag simulation: dnd-kit's `PointerSensor` needs `activationConstraint: { distance: 8 }` cleared — use `locator.hover()` → `page.mouse.down()` → several small incremental `page.mouse.move()` calls (not one large jump) ending over the target row → `page.mouse.up()`. Native `dispatchEvent`-based HTML5 drag simulation will **not** trigger this and must not be used.
- Requester view: `MyRequestsPage` "transfers" tab
- Approver view: `ApprovalsPage`, tab `approvals-tab-transfers` → `onTransferApprove`/`onTransferReject` handlers → `POST /api/hierarchy-transfers/{id}/approve` / `/reject`

- [ ] **Step 1: Identify two hierarchy nodes with distinct approvers**

  Read `backend/app/scripts/seed.py`'s hierarchy-node creation block and pick a source node (holding a soldier we can move) and a destination node with a commander/duty-manager distinct from the source's. Record node names/ids for UI navigation.

- [ ] **Step 2: Confirm the exact drop-target testid and drag affordance**

  Read `frontend/src/components/HierarchyTree.tsx`'s `DroppableNodeRow` (~line 127-202) and `DraggableSoldier` (~line 82-125) in full to pin down the literal testid strings and the `canEdit`/`can_edit` gating conditions (the drag handle only renders when these are true — confirm which role/scope satisfies them so the test logs in as the right actor).

- [ ] **Step 3: Write the spec skeleton with seam-inventory header**

  Include both interaction mechanisms and the explicit note that node-drag (`moveNode`) is out of scope.

- [ ] **Step 4: Test — create via click, approve, verify (baseline)**

  As the role confirmed in Step 2, navigate to `/team`, open the tree, use the click-based "quick add" or direct soldier-row action to select a soldier and destination node, fill `transfer-reason`, submit. Wait for `POST /api/hierarchy-transfers` 2xx. As the destination approver, navigate to `/approvals`, `approvals-tab-transfers`, approve. Wait for the approve endpoint 2xx. Refresh `/team` and assert the soldier now appears under the destination node.

- [ ] **Step 5: Test — create via drag-and-drop, approve, verify**

  Using a *second* soldier (to avoid colliding with Step 4's now-moved soldier), perform the mouse-based drag sequence from the soldier's `tree-soldier-${personal_number}` handle onto the destination node's row. Assert the `ConfirmDialog`/`transfer-reason` form opens as a result of the drop (proving `handleDragEnd` fired and routed into the same confirmation flow), fill the reason, submit, wait for `POST /api/hierarchy-transfers` 2xx. Approve as in Step 4. Assert the soldier appears under the destination node after refresh.

- [ ] **Step 6: Test — rejection path**

  Repeat the click-based creation with a third soldier, then have the destination approver reject with a required reason via `onTransferReject`. Assert the requester sees the rejection reason in `/my-requests`.

- [ ] **Step 7: Run against a freshly seeded DB, twice** (`--grep hierarchy_transfers`)

- [ ] **Step 8: Update coverage matrix and commit**

  Add a row noting both interaction mechanisms are covered, and that node-drag-to-move is a separate, uncovered feature (flag it as a follow-up gap, don't silently imply it's tested).

  ```bash
  git add frontend/tests/e2e/smoke/hierarchy_transfers.spec.ts frontend/tests/e2e/fixtures/auth.ts docs/e2e-coverage-matrix.md
  git commit -m "test: cover hierarchy transfer request via click and drag-and-drop, plus approve/reject"
  ```

---

### Task 4: Rank advancement — manual edit, interval config, and an actual triggered promotion (`frontend/tests/e2e/smoke/rank_advancement.spec.ts`)

**Scope:** the user wants promotion to genuinely happen and be observed, not scoped out. Promotion itself only fires from `_promote_due_soldiers()` inside the 24h-poll `rank_advancement_worker.py` — there is still no UI or HTTP trigger for it (confirmed again in the follow-up research pass). The honest way to "make it work end-to-end" without inventing a fake UI action: **manual UI edit sets the precondition, a small real backend utility runs the actual promotion function once, then the UI verifies the result.** This is a hybrid step and must be labeled as such in the spec comment — it is not a pure-browser action, but it exercises the real production promotion code path (not a mock), which is what actually proves promotion "works."

**Files:**
- Create: `frontend/tests/e2e/smoke/rank_advancement.spec.ts`
- Create: `backend/app/scripts/run_rank_advancement_once.py` — a small script that imports and calls `_promote_due_soldiers()` from `backend.app.rank_advancement_worker` once against `DATABASE_URL` and exits (mirrors the existing pattern of small one-shot scripts already in `backend/app/scripts/`; this is a genuinely useful ops utility too, not test-only scaffolding — an admin could run it manually to force a promotion pass without waiting for the daily poll)
- Modify: `frontend/src/pages/UnifiedSoldierModal.tsx` — no `data-testid` gaps found for the rank-editing controls (see Interfaces below, all already have testids); modify only if implementation reveals a missing one
- Modify: `docs/e2e-coverage-matrix.md`

**Interfaces (verified):**
- Manual rank edit: `UnifiedSoldierModal.tsx` — narrow flow `data-testid="rank-correction-toggle"` → form `data-testid="rank-correction-form"` → rank combo (bound to `profileRank`/`profileRankTrack`, no dedicated testid — select via its label/role) → submit `data-testid="rank-correction-submit"`. Full-profile flow has the same rank combo pattern, gated on `can_edit_rank_advancement`.
- Manual next-rank-date edit: `data-testid="next-rank-date-input"` (appears in both the narrow and full-profile forms) → same submit button → `PATCH /api/soldiers/{soldier_id}/profile` (fields `rank`, `rank_track`, `next_rank_date` gated by `rank_advancement_edit_authorized`, `backend/app/routes/soldiers.py:39,406-407,811,835`).
- Persisted-state indicator: `soldierData.next_rank_date_overridden` renders badge text `next_rank_date_manual` vs `next_rank_date_automatic` (~line 578) — use this to assert a manual edit actually flipped the flag, not just that the date changed.
- Promotion precondition (from worker tests): a soldier is due when `next_rank_date IS NOT NULL AND next_rank_date <= today`, `discharge_date IS NULL OR discharge_date > today`, `left_at IS NULL OR left_at > today`.
- Interval config: `SystemSettingsPage.tsx`, `RankAdvancementIntervalsSection` — inputs keyed by `draftKey(track, rank)`, **no testid exists yet**, must be added (see Step 3). API: `GET /api/soldiers/rank-ladder`, `PUT /api/soldiers/rank-advancement-intervals` (admin-only).

- [ ] **Step 1: Write `run_rank_advancement_once.py`**

  ```python
  """One-shot rank-advancement pass. Runs the same promotion logic the daily
  worker runs, without waiting for its poll interval. Safe to run manually
  in any environment — it only promotes soldiers already due."""
  from app.db.session import session_scope
  from app.rank_advancement_worker import _promote_due_soldiers

  def main() -> None:
      with session_scope() as session:
          _promote_due_soldiers(session)
          session.commit()

  if __name__ == "__main__":
      main()
  ```
  Read `backend/app/rank_advancement_worker.py`'s actual `_promote_due_soldiers` signature first (line ~84-97) — confirm whether it takes a session argument or opens its own `session_scope()` internally (the research pass's snippet suggests the latter — adjust the wrapper accordingly so it doesn't double-open a session). Test it directly: `cd backend && .venv\Scripts\python.exe -m app.scripts.run_rank_advancement_once` against the E2E database and confirm it exits 0 with no soldiers due (fresh seed has none due).

- [ ] **Step 2: Write the spec skeleton with seam-inventory header**

  Explicitly document the hybrid nature of the promotion test (UI setup → out-of-band script → UI verification) so a future reader isn't confused about why this spec shells out.

- [ ] **Step 3: Add testids to the interval inputs**

  Read `frontend/src/pages/SystemSettingsPage.tsx` around `RankAdvancementIntervalsSection` (~line 675-820), add `data-testid={\`rank-interval-months-${track}-${rank}\`}` to the months input and `data-testid={\`rank-interval-career-entry-${track}-${rank}\`}` to the checkbox, using the existing `draftKey(track, rank)` values.

- [ ] **Step 4: Test — admin edits an interval and it persists**

  As `admin`, navigate to `/admin/settings`, select the rank-advancement group, change one track/rank's months value, save, wait for `PUT /api/soldiers/rank-advancement-intervals` 2xx, reload, assert the value persisted.

- [ ] **Step 5: Test — manual rank and next-rank-date edit**

  As a user with `can_edit_rank_advancement` (check seed for which commander/duty-manager has this — the research pass confirmed the gate exists but not which seeded actor satisfies it; if none do, this step also needs an admin path since admins should implicitly qualify — verify), open a soldier via `UnifiedSoldierModal`, use `rank-correction-toggle` → `rank-correction-form`, set a new rank via the combo and a new `next-rank-date-input` value, submit via `rank-correction-submit`. Wait for the `PATCH .../profile` 2xx. Reload and assert both the new rank displays and the `next_rank_date_manual` badge text shows (proving `next_rank_date_overridden` flipped to true).

- [ ] **Step 6: Test — trigger and observe an actual promotion**

  As the same authorized actor, pick a *different* soldier (not the one from Step 5, to keep assertions independent) and set their `next-rank-date-input` to today's date via the same edit flow, submit, wait for the 2xx. Then run the one-shot script from the test (Node `child_process.execSync`, pointed at the same `backend\.venv\Scripts\python.exe -m app.scripts.run_rank_advancement_once`, with `DATABASE_URL` set to the E2E database the running backend actually uses — read it from the same env convention as `scripts/e2e.ps1`). After the script exits 0, reload the soldier's profile/modal in the browser and assert their `rank` field now shows the *next* rank in the ladder (per `get_next_rank`) and that `next_rank_date_overridden` reset to `false` (automatic) with a newly-computed future date — this proves the real promotion function ran and its effect is visible through the UI, not just that a script executed.

- [ ] **Step 7: Run against a freshly seeded DB, twice** (`--grep rank_advancement`)

  Note: Step 6 mutates real backend state outside the browser — when reseeding between runs, confirm the reseed also resets any soldier the previous run promoted (a `--clear` reseed does this automatically since it rebuilds the whole DB).

- [ ] **Step 8: Update coverage matrix and commit**

  Add a row noting the promotion assertion is a hybrid (UI + one-shot script) test and why.

  ```bash
  git add frontend/tests/e2e/smoke/rank_advancement.spec.ts backend/app/scripts/run_rank_advancement_once.py frontend/src/pages/SystemSettingsPage.tsx docs/e2e-coverage-matrix.md
  git commit -m "test: cover rank advancement manual edit, interval config, and a triggered promotion"
  ```

---

## Verification commands

Run from `frontend` unless noted, against a freshly reseeded E2E database (see Global Constraints):

```powershell
npx playwright test --grep "swaps|ranges|hierarchy_transfers|rank_advancement" --project=desktop --retries=0
```

Run each spec individually at least twice from a clean reseed before considering its task done. Before claiming any task complete, verify: fresh-database repeatability (2x), no reliance on `.first()` where DB accumulation could make it ambiguous, failure artifacts are produced on an intentionally-broken run, and the coverage matrix row is accurate. Treat timeouts or interrupted commands as unverified.
