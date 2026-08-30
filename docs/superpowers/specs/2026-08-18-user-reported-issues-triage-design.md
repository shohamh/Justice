# 2026-08-18 — Triage & Fix Plan for User-Reported Issues

## Status

Approved. 16 of 18 user-reported items are in scope and batched into six
implementation plans; 2 items are deferred. Batch execution order chosen by the
maintainer: **B (stop-the-bleeding first)** — Batch 2, then 1, 3, 4, 5, 6.

## Context

Feedback batch from real users of the army duty management system ("justice").
All 18 items were investigated end-to-end in the codebase (backend routes/
services/authz, frontend pages/components) on branch `triage-user-reported-issues`
(off `dev`). This spec records the triage disposition, the product decisions made
during brainstorming, and a per-batch implementation definition. Each batch is
executed as its own `writing-plans` implementation plan.

## Disposition table

| # | Report (translated) | Verdict | Action | Batch |
|---|---------------------|---------|--------|-------|
| 1 | "קוזקיש" cannot remove users | Backend by-design + UI bug | Commanders at מדור+ may delete soldiers in scope; gate the button; surface errors | 2 |
| 2 | Commanders can act only after soldiers join; only "קוזקיש" can approve their framework | Gate-stack bug in UI approval | Every in-scope commander can approve enrollment; rank-edit decoupled | 2 |
| 3 | (נבב) clicking a date to force a constraint: typed dates ignored | Confirmed | `DateInput` accepts typed dd/mm/yyyy, not only date-icon clicks | 1 |
| 4 | Commander can grant exemption without אג"מ approval | By-design, now re-decided | Grants become escalation → DM at מרכז+ approves | 2 |
| 5 | Soldier gets no feedback on requests (approved/rejected by whom) | Confirmed | Decider name + decision date surfaced on requests | 3 |
| 6 | Unclear what belongs in commander dashboard vs hierarchy page | Confirmed duplication | Dashboard = summaries/actions; /team = full management | 5 |
| 7 | Only direct commander sees/approves transfer requests into their team | List/notify vs authorize mismatch | All ancestors see + can approve descendant requests | 2 |
| 8 | Transfer request shows a number, not the soldier's name | Confirmed | `TransferOut` gains `soldier_name`; UI renders it | 1 |
| 9 | Wrong username shows "network error" | Confirmed (422 mapping) | Show "שם משתמש או סיסמה אינם נכונים" | 1 |
| 10 | No hierarchy shown when choosing announcement unit | Confirmed (admin flow) | Picker renders the real tree | 1 |
| 11 | Closing "intel" screen during algorithm run closes the run | Not mapped — ignored | — | — |
| 12 | אופיר דותן could not suggest a swap | Confirmed (`not_your_duty` on received duties) | Swap ask allowed on effective + draft duties | 4 |
| 13 | Others' swaps offer only "free", no date trade | Partial | Trade list includes drafts; clear empty-state | 4 |
| 14 | Upcoming duties not shown | Confirmed (published-only filter) | Upcoming widgets include `algorithm_draft` | 5 |
| 15 | Exemption/constraint date ranges look reversed | Display-path bug | Find + fix every swapped display path | 1 |
| 16 | Commanders see only exemptions/constraints, not duty history | Gate bug | Commanders see duty history of soldiers in scope | 5 |
| 17 | (שניר) document cancellation of exemptions/constraints | Write-only audit gap | Inline history on exemption/constraint records | 6 |
| 18 | Where is "הקפצה פיקודית"? | Built but flag-hidden | **Leave as-is** (deferred) | — |

## Product decisions (from brainstorming)

1. **Delete users (#1):** commanders at מדור and above, within their subtree.
2. **Enrollment approval (#2):** every commander whose commanded node covers the
   requested node (path containment) can approve — rank field editing is a
   separate capability and must not block approval.
3. **Exemption grants (#4):** commander grants are no longer immediate; they
   escalate for DM approval at מרכז and above.
4. **Transfers (#7):** all ancestor commanders see and can approve descendant
   transfer requests (list/notify aligned with `authorize`).
5. **Swap ask (#12):** allowed on duties received via swap (effective soldier)
   **and** on draft (`algorithm_draft`) duties.
6. **Cover trade (#13):** trade list includes draft duties; add clear empty-state
   messaging.
7. **Upcoming duties (#14):** include `algorithm_draft` alongside published.
8. **Dashboard (#6):** dashboard shows summaries/actions; full tree + soldier
   management lives only on `/team`.
9. **Duty history (#16):** any commander can view duty history of soldiers in
   their scope, independent of transparency settings.
10. **Audit visibility (#17):** inline history on the affected records, no global
    audit page.
11. **Hakpaza (#18):** leave hidden behind `forced_callup.enabled`; no work.
12. **Item #11:** ignore.

## Design calls (approved)

- **DC1 — Commander delete gate:** new `system_settings` key
  `soldiers.commander_delete_min_level` (default `מדור`), consuming the same
  level-check helper family as `commander_exemption_min_level`
  (`backend/app/services/authority.py`). Backend `authz.can()` for
  `Action.SOLDIER_DELETE` additionally requires a commanded node whose level is
  ≥ the configured key. Frontend: `/me` payload gains a capability flag
  (e.g. `can_delete_soldier`) so `TeamHierarchyPage` gates the remove button
  per-user instead of always rendering it, and `onRemove` gets try/catch +
  friendly error surfacing.
- **DC2 — Enrollment approval decoupling:** backend `ENROLLMENT_APPROVE` scope
  already permits every in-scope commander — no scope change. The defect is
  `EnrollmentApprovalModal.handleSaveAndApprove` unconditionally PATCHing rank
  fields, which trips the rank-advancement authority gate (מדור+). Fix: the
  pending-list payload exposes `can_edit_rank_advancement`; the modal sends rank
  fields only when true, otherwise approves directly. Raw `POST /approve` is
  unchanged and remains valid for in-scope commanders.
- **DC3 — Exemption escalation:** disabled the immediate grant path for
  commander exemption types (`is_commander_exemption`). `CommanderExemptionGrantForm`
  grants route through the existing escalation flow into an exemption request
  awaiting a DM at מרכז+ (new min-level check in the exemptions settings family).
  Immediate apply stays available to DMs at מרכז+ and admins only.
- **DC4 — Swap surfaces vs scoring isolation:** `effective_duty_spans`
  (`backend/app/services/scoring.py`) stays published-only — scoring/effort must
  not absorb drafts. A separate listing path for swap/cover surfaces includes
  `algorithm_draft` and resolves the effective soldier per day. `create_request`
  and the cover-offer path accept (a) a requester who is the effective soldier
  even when not the assignment owner, (b) draft status.
- **DC5 — Upcoming drafts:** `algorithm_draft` added only to display surfaces:
  the `UpcomingDutiesWidget` feed and `commander_dashboard` upcoming filters.
  Never to scoring/effort/eligibility inputs.
- **DC6 — Duty history gate:** fix the commander visibility gate so a commander
  sees the duty-history tab for soldiers in their commanded scope regardless of
  transparency settings.
- **DC7 — Inline audit:** new scoped read endpoint
  `GET /audit-logs?entity_type=&entity_id=` (authorized by actor scope) + a small
  history block rendered on exemption/constraint records. Backend audit writer
  unchanged.

## Batch definitions

Each batch = one `writing-plans` plan, implemented in its own worktree off `dev`,
merged to `dev` after review (per AGENTS.md).

### Batch 2 — Permissions (first)

**B2.1 — Commander delete (item 1)**
- `backend`: extend `Action.SOLDIER_DELETE` authorization in
  `backend/app/auth/authz.py` `can()` so commanders with a commanded node at
  `soldiers.commander_delete_min_level` (default מדור) or above can delete within
  that subtree. Add setting to `system_settings` (defaults + admin UI wiring in
  `frontend/src/pages/SystemSettingsPage.tsx`).
- `backend/app/routes/soldiers.py` delete endpoint: clearer 403 detail for
  denied scope.
- `frontend`: `GET /me` exposes `can_delete_soldier`; `TeamHierarchyPage.tsx`
  gates the remove button (line 185) + `onRemove` error handling.
- Tests: commander at מדור+ in scope → 200; commander below מדור → 403;
  out-of-scope → 403; frontend button visibility.

**B2.2 — Enrollment approval for all in-scope commanders (item 2)**
- `backend/app/routes/enrollment.py` pending-list payload gains
  `can_edit_rank_advancement` (per-request, using the existing authority check).
- `frontend/src/components/EnrollmentApprovalModal.tsx`: `handleSaveAndApprove`
  skips the rank PATCH when unauthorized; approve proceeds regardless. Error
  message specific to rank gate (`rank_advancement.unauthorized`) where still
  applicable.
- Tests: below-מדור commander approves without rank edit → 200; rank-edit
  authorized path unchanged; modal unit test for skip behavior.

**B2.3 — Exemption escalation (item 4)**
- `backend`: commander exemption types cannot be granted immediately by
  commanders; grant routes become escalation entries awaiting DM at מרכז+.
  New min-level key (e.g. `exemptions.commander_escalation_min_level`,
  default מרכז) enforced by `services/authority.py`-style check. Immediate apply
  remains for DMs at מרכז+ and admins.
- `frontend/src/components/CommanderExemptionGrantForm.tsx`: `applyImmediately`
  path disabled for commander exemption types → shows escalation flow.
- Tests: commander grants commander-exemption → produces pending request, not
  approval; DM below מרכז cannot approve; immediate apply only for DM מרכז+
  / admin.

**B2.4 — Ancestor visibility of transfers (item 7)**
- `backend/app/services/hierarchy_transfers.py`:
  `list_pending_for_approver` (+12) and `_notify_destination_approvers` (+58)
  use `path_ids` containment over the actor's commanded/DM-scope roots (matching
  `authorize` semantics at `authz.py`), instead of exact-node matching.
- Tests: ancestor commander sees descendant pending request; ancestor approves
  successfully; notifications include ancestors.

### Batch 1 — Quick UI fixes (second)

**B1.1 — Transfer soldier name (item 8)**
- `backend/app/routes/hierarchy_transfers.py`: `TransferOut` gains
  `soldier_name` populated from the Soldier join in `_out()`.
- `frontend/src/api/hierarchyTransfers.ts` type + `ApprovalsPage.tsx` render
  real name (fall back to current node name, mirroring the enrollment row).
- Tests: `TransferOut` includes a resolved name; `ApprovalsPage` renders it.

**B1.2 — Wrong-username message (item 9)**
- `frontend/src/pages/LoginPage.tsx`: 422 (and any other 4xx) → the
  `invalid_credentials` message "שם משתמש או סיסמה אינם נכונים" instead of the
  generic network error. Optionally add a format-hint key for non-digit input.
- Tests: `LoginPage.test.tsx` for a 422 response asserting the credentials
  message.

**B1.3 — Announcement unit picker hierarchy (item 10)**
- `frontend/src/components/HierarchyNodePickerModal.tsx`: render the tree with
  depth indentation + expandable nodes (reuse `HierarchyCheckboxTree` styling /
  buildForest), keeping search.
- Tests: picker renders parent/child structure for admins.

**B1.4 — Reversed date-range displays (item 15)**
- Audit every display path of exemption/constraint (and dismissal/call-up) date
  ranges across frontend components (`ExemptionsPanel`, `MyRequestsPage`,
  calendar, soldier modal panels). Where a range renders `start → end` inverted,
  or `end_date` is read directly for inclusive-date types, fix to the confirming
  convention (exclusive end only for assignments/cancellations via
  `lastDutyDay`). Report + fix each instance.
- Tests: unit test per fixed component asserting displayed order.

**B1.5 — DateInput typed dates (item 3)**
- `frontend/src/components/DateInput.tsx`: typed `dd/mm/yyyy` input must update
  the value (parse on change/blur, validate, propagate), so constraints/exemptions
  register dates typed directly during registration — not only date-icon clicks.
- Tests: typing a date updates value; invalid input behavior; icon picker
  unchanged.

### Batch 3 — Request feedback (third)

**B3.1 (item 5)**
- `backend`: add `decided_at` to `ExemptionRequest`
  (`db/models.py:691-728`) + Alembic migration; set it in
  `services/exemption_requests.py` approve/reject paths.
- `backend`: resolve decider names in request DTOs — `routes/constraints.py`
  (constraint `decided_by_name`, `commander_approved_by_name`), `routes/exemption_requests.py`
  (+ `decided_at`, names), mirroring the swaps pattern.
- `backend`: notification actor — persist a resolved `actor_name` into
  `Notification.metadata_json` at `create_notification` time
  (`services/notifications.py`) and expose it as `actor_name` on
  `NotificationOut` (`routes/notifications.py`). Resolution happens at write
  time so the bell/list renders without extra lookups.
- `frontend/src/pages/MyRequestsPage.tsx`: render decider name, decision date
  and (already-present) decision note per request row; `NotificationsPage`
  optionally shows actor name.
- Tests: migration; DTO name resolution; UI rendering.

### Batch 4 — Swaps (fourth)

**B4.1 — Swap ask on effective + draft duties (item 12)**
- `backend`: a request-list path for swap/cover surfaces that includes
  `published` + `algorithm_draft` and resolves the effective soldier per day.
  `services/swaps.create_request` accepts a requester who is the effective
  soldier for the shift day and accepts draft status.
- `frontend`: surfaces using this listing (SwapsPage / MyDutiesPage / detail
  panels) show ask-swap on received and draft duties.
- Tests: create_request for received duty → 200; draft duty → 200;
  non-effective requester → still `not_your_duty`; scoring untouched
  (published-only) regression test.

**B4.2 — Cover trade with drafts + empty-state (item 13)**
- `backend`: cover-offer path accepts draft duties from the offeror's list;
  `CoverOfferModal`/`OfferSwapModal` trade lists include draft duties.
- `frontend`: clear empty-state copy when no tradable duties (mirror
  `OfferSwapModal`'s existing messages in `CoverOfferModal`, which currently
  defaults to free with no explanation).
- Tests: trade offer with a draft duty; empty-state message renders; backend
  gate accepts drafts.

### Batch 5 — Dashboards & duty history (fifth)

**B5.1 — Dashboard / team split (item 6)**
- `frontend/src/pages/CommandDashboardPage.tsx`: remove the full interactive
  `HierarchyTree` panel (+173-182); replace with a compact read-only summary
  (counts + link to `/team`). Remove dead `activePanel`/`handleCardClick` code.
- Tests: dashboard no longer renders full tree; `/team` still hosts management.

**B5.2 — Upcoming duties include drafts (item 14)**
- `backend`: display-only upcoming feeds include `algorithm_draft` —
  `backend/app/services/scoring.py` `effective_duty_spans` stays published-only
  for scoring (DC4/DC5); the widget feed path and `commander_dashboard.py`
  upcoming filters (+143, +172, +305) add drafts.
- `frontend`: `UpcomingDutiesWidget` empty→non-empty with drafts.
- Tests: fixture with `algorithm_draft` shows in upcoming, excluded from scoring.

**B5.3 — Duty history visibility for commanders (item 16)**
- `backend`/`frontend`: commander in scope sees the duty-history tab and data for
  their own soldiers regardless of transparency settings; fix the gate
  (`UnifiedSoldierModal` `canViewAll`-driven tab) to derive from command scope.
- Tests: commander in scope sees history with transparency off.

### Batch 6 — Inline audit history (sixth)

**B6.1 (item 17)**
- `backend`: scoped read endpoint `GET /audit-logs?entity_type=&entity_id=`
  returning before/after + actor + timestamp + action for a record; authorized by
  actor scope on the entity.
- `frontend`: small history block on exemption/constraint record UIs (e.g. under
  the record row/type detail) showing who canceled/created + when.
- Tests: endpoint scope (own subtree); UI renders history.

## Cross-cutting constraints

- **Scoring/effort isolation:** draft status must never enter scoring, effort,
  or fairness inputs (DC4/DC5). Any listing change that feeds scoring must remain
  published-only.
- **Convention consistency:** `end_date` is exclusive only for assignments /
  cancellations; everything else (constraints, exemptions, dismissals, call-ups)
  is inclusive. Breadcrumb helpers: `lastDutyDay()`, `toExclusiveEndDate()` in
  `frontend/src/utils`.
- **RBAC:** all permission changes must go through `authz.authorize()`. UI
  gating must reflect the same capability the backend enforces (the current
  mismatch on the remove button is the failure mode being fixed).
- **Tests:** each batch lands with backend (unit + integration markers) and
  frontend (vitest) tests matching the repo conventions in AGENTS.md. CI runs
  ruff + mypy + pytest and lint + tsc + vitest.

## Risks

- **B2.3 (exemption escalation)** changes an approval behavior commanders are
  used to; escalation uses the existing two-step request state machine, but the
  "immediate" affordance removal must be communicated in UI copy.
- **B4 (swaps)** broadens the accept criteria for requests/offers; watch for
  double-swap / self-swap edge cases: a swap-ask on a received duty must target
  the underlying assignment correctly, and effective-duty resolution must be
  day-specific.
- **B5.2 (drafts in upcoming)** widens what users see before publishing; the
  proposal-review/publish flow already labels drafts as pending — keep that
  visible in the widgets.

## Out of scope / deferred

- Item 11 (algorithm "intel" screen) — reporter detail needed; ignored for now.
- Item 18 (הקפצה פיקודית discoverability) — leave as-is.
- No global audit-log admin page (B6 is inline-only by decision).