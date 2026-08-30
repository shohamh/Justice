# Handoff — User-Reported Issues: Spec Approved, Batches Ready to Execute

Handoff date: 2026-08-18

## What this is

Triage + fix plan for 18 user-reported issues in "justice" (army duty management
system, Hebrew UI / English code). The triage was brainstormed with the
maintainer and the spec was approved. Execution is split into six batches, each a
separate `writing-plans` implementation plan. **The full authoritative detail is
the spec doc — read it first:**

> **`docs/superpowers/specs/2026-08-18-user-reported-issues-triage-design.md`**
> (in the repo worktree)

This handoff exists so a fresh agent can pick up any batch. Do not re-derive
design decisions from the conversation; the spec is the source of truth.

## Active worktree / branch

- Worktree root: `C:\Users\Shoham\.paseo\worktrees\1n26l98r\solitary-cobra`
- Branch: `triage-user-reported-issues` (currently holds spec + handoff only —
  no code changes yet)
- Per AGENTS.md: feature batches branch off **`dev`** in their own worktree;
  finished work merges to `dev` with the **`merge-worktree-to-dev`** skill.
  Never commit directly to `dev`/`master`.

## Status of the spec

Written, self-reviewed, and approved by the maintainer. Not yet committed to git.
**The spec file should be committed (and this handoff saved) before agents start.**

## Execution order (maintainer chose option B: stop-the-bleeding first)

1. **Batch 2 — Permissions**: items 1, 2, 4, 7
2. **Batch 1 — Quick UI fixes**: items 8, 9, 10, 15, 3
3. **Batch 3 — Request feedback**: item 5
4. **Batch 4 — Swaps**: items 12, 13
5. **Batch 5 — Dashboards & duty history**: items 6, 14, 16
6. **Batch 6 — Inline audit history**: item 17

Items 11 (algorithm "intel" screen) and 18 (הקפצה פיקודית) are **out of scope** —
do not plan or implement them.

## Decisions locked during brainstorming (condensed)

| Item | Decision |
|------|----------|
| 1 (delete users) | Commanders at **מדור+** may soft-delete soldiers in their subtree. New setting `soldiers.commander_delete_min_level` (default מדור). `/me` gains `can_delete_soldier`; gating + error surface on the UI. |
| 2 (enrollment approval) | **Every in-scope commander** can approve enrollment (path containment). Rank-edit capability is decoupled — approve must NOT be blocked by missing rank-edit authority. Modal skips rank PATCH when unauthorized; pending-list payload exposes `can_edit_rank_advancement`. |
| 3 (DateInput) | Typed `dd/mm/yyyy` dates register in constraint/exemption forms during registration — not only date-icon clicks. |
| 4 (exemption grant) | Commander "grant" of commander exemption types **escalates** → approved by DM at **מרכז+**. Immediate apply only for DM מרכז+ and admins. |
| 5 (feedback) | Soldier sees who approved/rejected + when, per request. Add `decided_at` to `exemption_requests` (migration); resolve decider names in DTOs; notifications carry actor name. |
| 6 (dashboard) | Split roles: dashboard = summaries/actions; `/team` = full tree + soldier management. Remove duplicated tree + dead panel code. |
| 7 (transfers) | **All ancestor commanders** see and can approve descendant transfer requests (align list + notify with `authorize` path containment). |
| 8 (transfer name) | `TransferOut` gains `soldier_name`; UI renders the name, not a truncated id. |
| 9 (login error) | Wrong/malformed username shows "שם משתמש או סיסמה אינם נכונים" (map 422/other 4xx to invalid-credentials), never the generic network error. |
| 10 (announcement picker) | Admin unit picker renders the real hierarchy tree (not a flat list). |
| 12 (swap ask) | Swap ask allowed on **duties received via swap** (effective soldier resolves to the underlying assignment) **and on draft (**algorithm_draft**) duties**. |
| 13 (cover trade) | Cover/offer trade lists include **draft duties** + clear empty-state copy. |
| 14 (upcoming duties) | Upcoming widgets include `algorithm_draft` + published (match calendar). **Never** feeds scoring/effort. |
| 15 (reversed ranges) | Find + fix every display path that renders exemption/constraint date ranges reversed. |
| 16 (duty history) | Commanders see duty history of soldiers in their scope, independent of transparency settings. |
| 17 (audit visibility) | **Inline history** block on exemption/constraint records (scoped read endpoint `GET /audit-logs?entity_type=&entity_id=`); NO global audit page. |

## Approved design calls (DC1–DC7)

See spec "Design calls" section. Highlights:

- **DC1**: delete gate reuses the `authority.py` level-check pattern;
  UI gating mirrors backend capability exactly.
- **DC2**: no change to `ENROLLMENT_APPROVE` scope — the fix is the modal path.
- **DC3**: commander exemption grant → escalation state machine; DM at מרכז+ gate.
- **DC4/DC5**: scoring isolation — `effective_duty_spans` stays published-only;
  drafts enter only swap/cover/upcoming **display** surfaces.
- **DC6**: commander duty-history visibility derives from command scope, not
  transparency.
- **DC7**: audit writer untouched; new read endpoint + record-level UI history.

## Key file references per batch (from investigation)

- **Batch 2**: `backend/app/auth/authz.py` (`_DM_ACTIONS`, `_COMMANDER_ACTIONS`,
  `can()`), `backend/app/routes/soldiers.py:822-832`, `frontend/src/pages/TeamHierarchyPage.tsx:67-76,185`,
  `backend/app/routes/enrollment.py:251-265,281-291,383-402`, `frontend/src/components/EnrollmentApprovalModal.tsx:60-88`,
  `backend/app/routes/exemptions.py`, `frontend/src/components/CommanderExemptionGrantForm.tsx`,
  `backend/app/services/hierarchy_transfers.py:58-136`.
- **Batch 1**: `backend/app/routes/hierarchy_transfers.py:27-39`, `frontend/src/pages/ApprovalsPage.tsx:805`,
  `frontend/src/pages/LoginPage.tsx` (ErrKey union line 10), `frontend/src/components/HierarchyNodePickerModal.tsx:16-90`,
  `frontend/src/components/DateInput.tsx` (showPicker at 156-161), exemption/constraint display paths
  (`ExemptionsPanel`, `MyRequestsPage.tsx`, soldier modal panels), `frontend/src/utils/formatDate.ts:58-64` (`lastDutyDay`).
- **Batch 3**: `backend/app/db/models.py:665-728`, `backend/app/services/constraints.py:124-242`,
  `backend/app/services/exemption_requests.py:158-257`, `backend/app/services/notifications.py:284-343`,
  `backend/app/routes/notifications.py:21-31,172-178`, `frontend/src/pages/MyRequestsPage.tsx:166-284,443-461`.
- **Batch 4**: `backend/app/services/swaps.py:61-142` (`create_request` gates at 88-101),
  `backend/app/services/scoring.py:108-201` (`effective_duty_spans`, published-only at 119-123),
  `frontend/src/pages/SwapsPage.tsx:158-163`, `frontend/src/components/AskSwapModal.tsx`,
  `frontend/src/components/CoverOfferModal.tsx` (default `free`, line 19), `frontend/src/components/OfferSwapModal.tsx:141-147,273-280`.
- **Batch 5**: `frontend/src/pages/CommandDashboardPage.tsx:136-182,243`, `frontend/src/pages/TeamHierarchyPage.tsx:86`,
  `backend/app/services/commander_dashboard.py:140-152,172,296-354`, `backend/app/routes/commander_dashboard.py:213`,
  `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx:26-28`, soldier-modal duty-history gate
  (`UnifiedSoldierModal.tsx` tabs / `canViewAll`; `backend/app/routes/soldiers.py:572-607` duty-history endpoint).
- **Batch 6**: `backend/app/audit/writer.py`, `db/models.py:86` (AuditLog), bug-report snapshot
  (`routes/bug_reports.py` `_audit_snapshot`) as the only current consumer.

## Cross-cutting constraints (do not violate)

- **Scoring/effort isolation**: drafts never enter scoring/effort/fairness.
- **Convention**: `end_date` exclusive ONLY for assignments/cancellations;
  constraints/exemptions/dismissals/call-ups are inclusive.
- **RBAC**: all permission changes flow through `authz.authorize()`; UI gating
  MUST mirror backend capability (today's remove-button mismatch is the failure
  mode being fixed).
- **Tests**: backend (ruff, mypy, pytest markers) + frontend (lint, tsc, vitest)
  per AGENTS.md. Zero lint warnings enforced.
- No new global audit page; no hakpaza work; no item-11 work.

## Suggested skills for agents picking up a batch

- `brainstorming` — only if a batch still has an open design question (re-read
  the spec first; most decisions are closed).
- `writing-plans` — produce the per-batch implementation plan before coding
  (AGENTS.md mandates plan-first execution via subagents).
- `test-driven-development` / `tdd` — write tests first for the fixes.
- `verification-before-completion` — confirm tests/lint/typecheck pass before
  claiming done.
- `merge-worktree-to-dev` — integrate finished batch into `dev` (project skill;
  never merge to `master`).
- `executing-plans` / `subagent-driven-development` — when executing a written
  plan.

## First steps for the next agent

1. Read the spec doc (path above).
2. Commit spec + this handoff on the current branch if not done.
3. For the chosen batch, create a fresh worktree off `dev`, write its plan
   (`writing-plans`), implement with TDD, verify, and merge via
   `merge-worktree-to-dev`.