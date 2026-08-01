# Mitvachim Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add future-range excusal requests, immediate reserve self-drop, scoped approval, and automatic reserve promotion behind the existing mitvachim feature flag.

**Architecture:** Add one `RangeExcusalRequest` table and a focused `range_excusal` service. Primary excusal is pending until a DM or qualified commander decides; approval atomically removes the primary and promotes the highest-ranked currently assigned eligible reserve. Reserve excusal is immediately approved and removes only that reserve. Extend the existing ranges router/API and keep all UI in `RangesPage`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest, React/TypeScript, TanStack Query, Vitest.

## Global Constraints

- Keep Hebrew UI copy and English identifiers/comments.
- Gate every new route with `mitvachim.enabled` and return the existing not-found response when disabled.
- Preserve `RangeAssignment` rows and roster state until primary excusal approval.
- Reuse Phase 2 candidate conflict filters and tier ordering; restrict promotion candidates to current reserve assignments.
- Never change duty swap or duty reserve behavior.
- Work in the isolated `feature/mitvachim-phase3` worktree and commit each independently testable task.

---

## Task 1: Excusal model, settings, action, and migration

**Files:**
- Modify: `backend/app/db/models.py` — add `RangeExcusalRequest`, status enum/string fields, and excusal notification types.
- Modify: `backend/app/auth/authz.py` — add `Action.RANGE_EXCUSAL_DECIDE` to DM and commander buckets.
- Modify: `backend/alembic/versions/7f2c1a9d4e6b_add_range_excusal_requests.py` — create table, indexes, and setting seed.
- Modify: `backend/app/routes/public_settings.py` — expose no new public key unless required by existing settings conventions; approval threshold is server-side.
- Test: `backend/tests/unit/test_range_models.py`, `backend/tests/unit/test_range_authorization.py`.

**Interfaces:** Produces `RangeExcusalRequest`, a partial unique index for one pending request per assignment, `Action.RANGE_EXCUSAL_DECIDE`, and `mitvachim.excusal_approve_min_commander_level` defaulting to `מדור`.

- [ ] Write model and authorization tests for pending uniqueness, nullable decision fields, DM scope, and commander threshold.
- [ ] Run the focused tests and verify they fail for missing model/action behavior.
- [ ] Implement the model, enum values, migration, setting seed, and action buckets following existing SQLAlchemy/Alembic patterns.
- [ ] Run focused tests and migration validation.
- [ ] Commit: `feat: add range excusal request model and authorization`

## Task 2: Excusal service and reserve promotion

**Files:**
- Create: `backend/app/services/range_excusal.py` — request, decide, promotion, and reserve self-drop functions.
- Modify: `backend/app/services/range_auto_assign.py` — expose a small reusable reserve-candidate filtering/ranking helper without changing existing auto-assignment behavior.
- Test: `backend/tests/unit/test_range_excusal.py`.

**Interfaces:**
- `request_primary_excusal(session, assignment, reason, requested_by) -> RangeExcusalRequest`
- `request_reserve_excusal(session, assignment, reason, requested_by) -> RangeExcusalRequest`
- `decide_primary_excusal(session, request, approve, decided_by, note=None) -> RangeExcusalRequest`
- `list_pending_excusal_requests(session, event) -> list[RangeExcusalRequest]`

- [ ] Write failing tests for future-date and ownership-independent service guards, duplicate pending requests, rejection, approval with the correct tier-ranked reserve, approval without an eligible reserve, and immediate reserve removal.
- [ ] Run `pytest tests/unit/test_range_excusal.py -q` and verify the new tests fail.
- [ ] Implement reason validation, event/assignment status checks, transactional locking, and notifications for requester, promoted soldier, and DM no-backfill outcome.
- [ ] Reuse the Phase 2 filters/ranking against only assigned, non-draft reserves and re-check conflicts at decision time.
- [ ] Run unit tests and verify no unrelated range auto-assign tests regress.
- [ ] Commit: `feat: implement range excusal and reserve promotion service`

## Task 3: API routes and schemas

**Files:**
- Modify: `backend/app/routes/ranges.py` — add excuse, pending-list, and decide endpoints plus response schemas and authorization helpers.
- Test: `backend/tests/integration/test_range_excusal_api.py`.

**Interfaces:**
- `POST /ranges/{event_id}/assignments/{assignment_id}/excuse` body `{reason}`.
- `GET /ranges/{event_id}/excusal-requests` returns scoped pending requests.
- `POST /ranges/{event_id}/excusal-requests/{request_id}/decide` body `{approve, note?}`.

- [ ] Add integration tests for feature-flag 404, assignment ownership, future-event validation, DM and commander authorization, event/request mismatch, and response payloads.
- [ ] Run focused integration tests and verify route failures.
- [ ] Implement routes using existing `_require_enabled`, `_load_event`, `authorize`, and bespoke commander threshold checks; map service validation errors to 400 and missing resources to 404.
- [ ] Run the focused integration suite.
- [ ] Commit: `feat: expose range excusal API routes`

## Task 4: Frontend API and RangesPage workflow

**Files:**
- Modify: `frontend/src/api/ranges.ts` — add request/response types and three API wrappers.
- Modify: `frontend/src/pages/RangesPage.tsx` — add reason dialog/form, self-excusal controls, pending review queue, and outcome banners.
- Modify: `frontend/src/i18n/he.json` — add Hebrew strings if the page’s existing conventions require translation keys.
- Test: `frontend/src/pages/RangesPage.test.tsx` or the existing ranges page test file.

**Interfaces:** Add `RangeExcusalRequest`, `RangeExcusalDecision`, `excuseRangeAssignment`, `getRangeExcusalRequests`, and `decideRangeExcusal`.

- [ ] Write Vitest coverage for non-empty reason gating, primary pending state, reserve immediate confirmation, queue rendering, approve/reject calls, and promoted versus no-backfill outcomes.
- [ ] Run the focused frontend tests and verify failures.
- [ ] Implement accessible inline/dialog reason entry, disable submit for whitespace-only reasons, invalidate event and request queries after mutations, and prevent row actions from triggering event selection.
- [ ] Show the excuse action only for the logged-in soldier’s own future assignment; show review actions only to users who can decide.
- [ ] Run focused Vitest, typecheck, and lint.
- [ ] Commit: `feat: add range excusal controls and review queue`

## Task 5: End-to-end verification and handoff

**Files:** No source changes expected; update tests only if verification exposes a concrete defect.

- [ ] Run backend focused range tests, then `pytest -q` from `backend`.
- [ ] Run frontend `npm test`, `npm run typecheck`, and `npm run lint` from `frontend`.
- [ ] Review the diff for scope leaks, migration correctness, race handling, and Hebrew UI copy.
- [ ] Use the project review workflow before merging the worktree into `dev`; do not merge directly to `master`.


