# Homepage Performance and Scoring Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce homepage request critical-path time and make scoring projection fallbacks diagnosable without changing visible scoring semantics.

**Architecture:** Reuse already-loaded React Query data across homepage children, make independent calendar resources load concurrently, and add a focused measurement seam that reports request count and completion timing. Preserve the existing legacy scoring fallback as a correctness safety net while exposing the concrete projection-state reason in diagnostics/log context.

**Tech Stack:** React, TanStack Query, TypeScript, FastAPI, SQLAlchemy, Vitest, pytest.

**Spec:** Approved in chat on 2026-09-14.

## Global Constraints

- Preserve Hebrew/RTL UI, authorization, and scoring response semantics.
- Do not touch unrelated dirty worktree changes.
- Verify frontend checks from `frontend` and backend checks from `backend`.
- Do not claim performance improvement without before/after measurements.

### Task 1: Remove duplicate homepage alert requests

**Files:**
- Modify: `frontend/src/components/dashboard/AlertBanners.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`
- Test: `frontend/src/components/dashboard/AlertBanners.test.tsx`

- [ ] Write a test proving alert rendering consumes supplied duties/settings without issuing its own fetches.
- [ ] Run the focused test and confirm it fails against the current component contract.
- [ ] Pass the existing homepage duties/settings into `AlertBanners` and remove its duplicate effect fetch.
- [ ] Run the focused test and confirm it passes.

### Task 2: Parallelize calendar resource loading

**Files:**
- Modify: `frontend/src/api/calendarData.ts`
- Test: `frontend/src/api/calendarData.test.ts`

- [ ] Add a test proving ranges start before the calendar request resolves and remain optional on failure.
- [ ] Run it red.
- [ ] Implement concurrent loading with `Promise.all` while retaining calendar-required error behavior.
- [ ] Run the focused tests green.

### Task 3: Add an observable homepage performance harness

**Files:**
- Create: `frontend/tests/homepage-performance.spec.ts`
- Modify: `frontend/playwright.config.ts` only if existing fixtures require a dedicated project

- [ ] Reuse existing authenticated fixtures and record request count, per-request duration, and page milestones.
- [ ] Assert the harness produces a nonzero request set and a stable homepage completion marker.
- [ ] Run the harness against the current implementation to capture the baseline.

### Task 4: Diagnose and correct projection fallback state

**Files:**
- Modify: `backend/app/services/scoring.py` only after evidence identifies a code defect
- Test: focused scoring service or route test matching the identified defect

- [ ] Inspect the running service environment and projection state, keeping credentials redacted.
- [ ] Add a failing regression test only for a confirmed defect.
- [ ] Apply the smallest root-cause fix, or document the state as operational backfill work if no code defect exists.
- [ ] Re-run scoring tests and the homepage harness.

### Task 5: Final verification

- [ ] Run focused frontend and backend tests.
- [ ] Run frontend lint/typecheck and focused backend lint/type checks as applicable.
- [ ] Run the performance harness again and compare request count and completion timing.
- [ ] Confirm no debug instrumentation remains and report verified, partial, and unverified results separately.
