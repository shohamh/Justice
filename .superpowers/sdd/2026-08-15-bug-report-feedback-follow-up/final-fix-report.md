# Final fix wave report

## Scope

This wave addresses all three Important findings from the final whole-branch review:

1. Feedback screenshot capture no longer mutates visible live scroll content while `html-to-image` runs asynchronously.
2. The range-attendance worker unit regressions caused by the elapsed-event transition call are repaired with explicit ordering, commit, and logging coverage.
3. Elapsed planned range completion is atomic and idempotent across concurrent PostgreSQL sessions, including its audit side effect and changed-row count.

## Finding 1: capture-only feedback screenshot representation

The installed `html-to-image` version is `1.11.11`. Its public `Options` type has no `onClone` hook, and its implementation applies `options.style` only to the root clone after recursively copying descendant computed styles. That makes the earlier temporary inline transform unsafe for the live page and makes a descendant clone-time callback unavailable.

`BugReportTrigger` now:

- freezes the app shell's `scrollTop` and `scrollLeft` before asynchronous work;
- clones `document.body` before adding any capture host;
- stages that copy in a connected, inert, `aria-hidden`, pointer-inert host translated far off-screen so `getComputedStyle` remains available to this library version;
- translates only `[data-bug-report-scroll-content]` in the staged copy;
- leaves the fixed header, live wrapper transform, live `scrollTop`, and live `scrollLeft` unchanged;
- passes the staged copy, never `document.body`, to `toPng`;
- retains root-transform window-scroll fallback for pages without the app shell markers;
- removes the staged copy in `finally`, including rejection and timeout paths;
- keeps capture-before-modal, six-second timeout, null-screenshot fallback, spinner, and modal-opening behavior unchanged.

The regression holds `toPng` unresolved and proves simultaneously that the live wrapper remains `scale(1)`, live scroll offsets remain `300`/`40`, the staged wrapper is `translate(-40px, -300px)`, the staged header remains `scale(1)`, and the staged node is removed after capture resolves.

### TDD evidence

RED:

```text
npx vitest run src/components/BugReportTrigger.test.tsx -t "translates only a capture clone"
1 failed: expected the captured node not to be document.body
```

GREEN:

```text
npx vitest run src/components/BugReportTrigger.test.tsx
1 file passed, 10 tests passed
```

The suite emits the existing React Router future-flag and missing test i18n-instance warnings.

## Finding 2: range-attendance worker unit regressions

The two failing unit tests supplied an opaque `object()` session and mocked only attendance marking. The worker now also invokes `mark_past_range_events_completed` and commits after both service calls, so those doubles no longer represented the worker's session/service contract.

The repaired coverage uses a minimal session double with `commit()`, stubs both service boundaries, and proves:

- elapsed-event completion runs first;
- attendance auto-marking runs second with the same session;
- one commit runs after both operations;
- non-zero lifecycle and attendance counts each produce their existing log message;
- the zero/zero path still commits and emits no informational log.

Production worker behavior was not weakened or reordered.

### Regression and GREEN evidence

Before test repair:

```text
backend/tests/unit/test_range_attendance_worker.py
2 failed, 1 passed
AttributeError: 'object' object has no attribute 'execute'
```

After repair:

```text
backend/tests/unit/test_range_attendance_worker.py
3 passed
```

## Finding 3: concurrent elapsed-event transition

The previous implementation selected every eligible planned event, mutated loaded ORM objects, then inserted audits. Two sessions could both read the same `planned` row before either flushed, causing both callers to return `1` and both to append `range_event.complete` audits.

The service now executes one PostgreSQL atomic conditional statement:

```sql
UPDATE range_events
SET status = 'completed'
WHERE status = 'planned' AND date < :today
RETURNING id
```

Only IDs actually changed by that statement receive an audit row, in the same transaction. A concurrent caller waits for the row update and re-evaluates the conditional predicate; after the first commit it returns no ID, counts zero, and writes no audit. Rollback still rolls back both the status and audit together.

The date/status semantics are unchanged: only `date < today` and `planned` rows transition; today's, future, completed, and cancelled events are untouched. Route authorization still runs before this mutation, and existing completed-event update/assignment guards remain intact.

### TDD evidence

The focused two-session PostgreSQL regression forces both old candidate reads into the same race window.

RED:

```text
expected sorted results [0, 1], received [1, 1]
```

GREEN after the atomic update:

```text
1 passed
```

It also asserts the persisted status is `completed` and exactly one `range_event.complete` audit exists for the event.

## Verification

Focused wave checks:

- `BugReportTrigger.test.tsx`: 10 passed.
- `test_range_event_status.py`, `test_range_attendance_auto_mark.py`, and `test_range_attendance_worker.py`: 17 passed.
- Worker unit regression file alone: 3 passed.

Integrated affected frontend command:

```text
11 files passed, 114 tests passed
```

This includes the plan's nine-file integration list plus `UnitCalendar.test.tsx` and `Combobox.test.tsx`. Existing non-failing output remains: React `act(...)` warnings in `ShiftDetailPanel`, jsdom `AggregateError` network output in `UnitCalendar`, React Router future-flag warnings, and missing test i18n-instance warnings.

Integrated affected backend command:

```text
33 passed
```

This includes range status, range attendance auto-marking, soldier approval coverage, and the worker unit file. The only warning is the existing `testcontainers.postgres` deprecation warning.

Static checks:

- `npm run typecheck`: passed (`tsc --noEmit`).
- `npx eslint src --max-warnings 0`: passed, exit 0.
- `git diff --check`: passed before this report and will be rerun before commit.

## Playwright status and environment blocker

Playwright is **not green** and is not claimed as such.

The original npm invocation parsed the pipe in `--grep "feedback|screenshot"` as a normal argument and began the complete 17-test suite; that mis-scoped run was stopped. The explicit command was then used:

```text
npx playwright test tests/e2e/feedback_screenshot.spec.ts
```

Result: one test failed before reaching the screenshot step. Login remained at `http://localhost:5173/login` and the rendered page showed `שגיאת רשת. נסה שוב.`. The listeners on ports 5173 and 8000 belong to the main checkout, not this worktree:

```text
C:\Users\Shoham\workspace\Justice\frontend\...\vite.js
C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe -m uvicorn ... --port 8000
```

Starting this worktree's `dev.ps1` would stop/replace those already-running services, so it was not done without authorization. Browser-level validation of the lower-page magenta marker therefore remains blocked by the unavailable worktree-local authenticated stack.

## Changed files

- `frontend/src/components/BugReportTrigger.tsx`
- `frontend/src/components/BugReportTrigger.test.tsx`
- `backend/app/services/ranges.py`
- `backend/app/services/tests/test_range_event_status.py`
- `backend/tests/unit/test_range_attendance_worker.py`
- `.superpowers/sdd/2026-08-15-bug-report-feedback-follow-up/final-fix-report.md`

The pre-existing untracked plan at `docs/superpowers/plans/2026-08-15-bug-report-feedback-follow-up.md` is preserved and excluded from this fix-wave commit.
