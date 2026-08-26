# Admin profiles, role promotion, and privileged request cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add admin-wide profile editing, password-confirmed admin promotion, scoped cancellation of personal requests, and senior-only commander approval.

**Architecture:** Keep authorization in shared backend predicates and return per-record capabilities to the frontend. Use existing audit, notification, profile, and modal patterns; add only the role-promotion endpoint and cancellation metadata needed by the new policy.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React, TypeScript, Vitest, React Query, i18next.

**Spec:** `docs/superpowers/specs/2026-08-26-admin-profiles-and-request-cancellation-design.md`

## Global Constraints

- Admins may edit every existing profile field, including rank, rank-track/general rank, officer status, and next-rank date.
- Promotion requires the acting administrator's current password and explicit confirmation; passwords never enter audit data.
- Cancellation authorization applies to both pending and approved records; the extreme-action reason modal is required only for approved records.
- Commander approval requires commander scope at מדור or above; duty-manager approval remains unchanged.
- Preserve unrelated dirty worktree changes and never commit directly to `dev` or `master`.

## Files and responsibilities

- `backend/app/services/authority.py`: shared seniority/scope predicates.
- `backend/app/routes/soldiers.py`, `backend/app/services/soldiers.py`: admin profile bypass and role promotion.
- `backend/app/routes/exemptions.py`, `backend/app/services/exemptions.py`: exemption cancellation capability and privileged cancellation.
- `backend/app/routes/constraints.py`, `backend/app/services/constraints.py`: constraint cancellation capability and privileged cancellation.
- `backend/app/routes/exemption_requests.py`: commander-step approval threshold.
- `frontend/src/components/UnifiedSoldierModal.tsx`, `frontend/src/components/ExemptionsPanel.tsx`: profile, role, and exemption UI.
- `frontend/src/api/{soldiers,exemptions,constraints}.ts`: typed contracts.
- Relevant backend route/service tests and frontend component/page tests: regression coverage.

### Task 1: Admin profile editing and password-confirmed promotion

**Files:**
- Modify: `backend/app/routes/soldiers.py`, `backend/app/services/soldiers.py`, `backend/app/routes/auth.py` or a focused soldiers route helper.
- Modify: `frontend/src/api/soldiers.ts`, `frontend/src/components/UnifiedSoldierModal.tsx`, `frontend/src/pages/TeamHierarchyPage.tsx`.
- Test: `backend/app/routes/tests/test_soldiers_routes.py` or the existing soldiers route test file; `backend/app/services/tests/test_soldiers.py`; matching frontend modal/page tests.

- [ ] Write failing tests proving admins can PATCH rank/rank-track/next-rank-date and that a non-admin cannot; prove promotion rejects an incorrect current password and accepts a correct one only for an admin actor.
- [ ] Run the focused tests and verify they fail for the missing admin bypass/endpoint.
- [ ] Implement the admin bypass using the existing rank advancement authority seam, add an admin-only promotion request with current-password verification, audit the role change without password data, and extend the frontend editor/action/modal.
- [ ] Run focused backend/frontend tests, typecheck the touched frontend, and refactor only after green.
- [ ] Commit the task with `feat: allow admin profile editing and admin promotion`.

### Task 2: Shared cancellation authority and exemption cancellation

**Files:**
- Modify: `backend/app/services/authority.py`, `backend/app/services/exemptions.py`, `backend/app/routes/exemptions.py`.
- Modify: exemption DTOs/API and `frontend/src/components/ExemptionsPanel.tsx`.
- Test: exemption authority/service/route tests and `ExemptionsPanel` tests.

- [ ] Write failing tests for commander מדור threshold, duty-manager ענף threshold, out-of-scope denial, pending cancellation permission, approved cancellation requiring a reason, notification body, audit data, and history response.
- [ ] Run those tests and confirm expected failures.
- [ ] Add the shared predicate and enforce it at the route/service boundary; expose `can_cancel` and cancellation reason metadata; preserve existing self-service behavior and eligibility invalidation.
- [ ] Add the approved-only extreme-action modal with required reason and wire pending cancellation to its existing behavior.
- [ ] Run focused tests and commit `feat: add scoped exemption cancellation`.

### Task 3: Personal-constraint cancellation and commander approval threshold

**Files:**
- Modify: `backend/app/services/constraints.py`, `backend/app/routes/constraints.py`, `backend/app/routes/exemption_requests.py`.
- Modify: `frontend/src/api/constraints.ts`, `frontend/src/components/UnifiedSoldierModal.tsx`, `frontend/src/pages/ApprovalsPage.tsx`, and shared request/history display components as needed.
- Test: constraints, exemption-request, approvals-page, and soldier-modal tests.

- [ ] Write failing tests for pending/approved privileged constraint cancellation, required approved-cancellation reason, reason visibility, and junior-commanders being unable to approve while duty managers retain current approval.
- [ ] Run the tests and confirm they fail for the current broad approval/cancellation behavior.
- [ ] Reuse the shared cancellation predicate, persist cancellation reason and notification/history data, and replace only the commander-step check with the מדור-and-above commander predicate while leaving duty-manager logic intact.
- [ ] Align list/count/capability fields and frontend approval/cancellation affordances with backend results.
- [ ] Run focused tests and commit `feat: scope constraint cancellation and approval authority`.

### Task 4: Integration verification and documentation

**Files:**
- Modify: only touched tests/contracts/i18n files required by verification.

- [ ] Run all focused backend tests for soldiers, authority, exemptions, constraints, and exemption requests.
- [ ] Run relevant frontend Vitest suites, `npm run typecheck`, and `npm run lint`.
- [ ] Search for stale broad commander approval/cancellation checks and remove any duplicate UI-only role inference.
- [ ] Review the diff for secrets, unrelated changes, and missing Hebrew translations; commit any final test-only/i18n fixes as `test: verify admin and request authority flows`.
