# Bug Report Batch Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 independent bug reports collected from users on 2026-09-08, spanning the dashboard, bug-report admin table, swap-request lifecycle, error messaging, exemption granting, RBAC for exemption approvals, and duty-instructions notifications.

**Architecture:** Each bug lives in a different subsystem with no shared code path, so each task below is a fully independent, separately-committable change. There is no shared new abstraction introduced — every fix reuses an existing helper/pattern already present in the codebase (`translateApiError`, `create_notification`, `senior_commander_approval_authorized`, etc.).

**Tech Stack:** Backend: Python, FastAPI-style routers, SQLAlchemy 2.0 declarative models, Pydantic, pytest. Frontend: React + TypeScript, TanStack Query, react-i18next, Vitest.

**Spec:** This plan has no separate spec document — the "spec" is the raw Hebrew bug-report list reproduced per-task below (translated to English inline). This plan argues directly from those reports.

## Global Constraints

- Hebrew UI / English code: all new UI copy is Hebrew, added via `frontend/src/i18n/he.json` under the existing namespace conventions (`errors.*`, `swaps.*`, `exemptions.*`, `bug_reports.*`). Do not hardcode new Hebrew strings inline in components — add an i18n key.
- Never show a raw backend `detail` code to the user directly — always route it through `frontend/src/utils/translateApiError.ts` (`translateApiError(err, t, fallback?)`), adding an `errors.<code>` key when one doesn't exist yet.
- Backend errors are raised as `HTTPException(status_code=..., detail="<snake_case_code>")`; new domain errors follow the same convention (short, translatable, snake_case).
- Every backend service change lands with a service-level pytest using the existing fixtures (`client: TestClient`, `admin_session: Session`, `create_soldier`, `auth_headers` from `tests.helpers`) — no new test infrastructure.
- Small, single-purpose commits per task step, per the repo's branch workflow (`CLAUDE.md`): this work happens on a feature branch off `dev`, never committed directly to `dev`/`master`.
- Run `pytest -q` (backend) and `npm run typecheck` / relevant `npm test` file (frontend) before each task's commit — don't rely on the full `--slow` suite mid-task.

---

## Task 1: Dashboard scoring — stop showing a generic error to soldiers without permission

**Bug report (Hebrew):** "כרגע עבור חייל רגיל שאין לו הרשאות לראות נתוני ניקוד בדאשבורד כתוב שגיאה בטעינת נתוני ניקוד וגם אם יש דברים שאין לחייל הרשאה לראות ואנחנו יודעים את זה בפרונטאנד אז אולי לא צריך לשלוח את הבקשות האלה לבאקאנד" — a regular soldier without permission to view scoring data sees a generic "error loading scoring data" banner; since the frontend already knows the user lacks permission, it shouldn't even issue those requests.

**Root cause:** `frontend/src/pages/HomePage.tsx:210-240` fires four scoring queries (`transparencyQuery`, `breakdownQuery`, `burdenShareQuery`, `burdenShareBreakdownQuery`) unconditionally (`enabled: !!user`), even though `user.can_view_transparency` (already defined on the `User` type, `frontend/src/api/auth.ts:53`, and already used to gate rendering in `HomePage.tsx:542`, `TransparencyPage.tsx:303/312`, `UnifiedNav.tsx:75`) tells the frontend in advance the backend will 403 (`backend/app/routes/scoring.py:124/140` raise `HTTPException(403, detail="transparency_hidden")` / `detail="forbidden"`). The queries then fail and `hasScoreLoadError` ORs the four `isError` flags into one generic `t("home.score_load_error")` banner (`HomePage.tsx:467-471`), regardless of cause.

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx:210-240` (query `enabled` flags), `:236-240` (`hasScoreLoadError`), `:467-471` (banner)
- Modify: `frontend/src/i18n/he.json` (add `home.score_hidden` key if not present)
- Test: `frontend/src/pages/HomePage.test.tsx` (create if it doesn't already cover this; otherwise extend the existing HomePage test file — check with `Glob frontend/src/pages/HomePage.test.tsx` first)

**Interfaces:**
- Consumes: `user.can_view_transparency: boolean | undefined` (already on the `User` type from `frontend/src/api/auth.ts`)
- Produces: no new exports — purely internal to `HomePage.tsx`

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/HomePage.test.tsx` (create the file following the existing mocking pattern used by sibling page tests — mock `useAuth()` to return a user with `can_view_transparency: false`, and spy on the scoring API modules to assert they are never called):

```tsx
it("does not fetch scoring data and shows no generic error for a user without transparency permission", async () => {
  const getTransparency = vi.spyOn(scoringApi, "getTransparency");
  const getBreakdown = vi.spyOn(scoringApi, "getBreakdown");
  const getBurdenShare = vi.spyOn(scoringApi, "getBurdenShare");
  const getBurdenShareBreakdown = vi.spyOn(scoringApi, "getBurdenShareBreakdown");
  mockUseAuth.mockReturnValue({ user: { ...baseUser, can_view_transparency: false } });

  renderHomePage();

  await waitFor(() => expect(screen.queryByText("שגיאה בטעינת נתוני הניקוד")).not.toBeInTheDocument());
  expect(getTransparency).not.toHaveBeenCalled();
  expect(getBreakdown).not.toHaveBeenCalled();
  expect(getBurdenShare).not.toHaveBeenCalled();
  expect(getBurdenShareBreakdown).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- HomePage.test.tsx` (from `frontend/`)
Expected: FAIL — the spies register calls because the queries currently fire unconditionally.

- [ ] **Step 3: Gate the four queries and split the error state**

In `frontend/src/pages/HomePage.tsx`, change lines 210-240:

```tsx
const canViewScoring = user?.can_view_transparency !== false;

const transparencyQuery = useQuery({
  queryKey: queryKeys.transparency(),
  queryFn: getTransparency,
  select: (out) => out.rows,
  enabled: canViewScoring,
});
const transparencyRows = useMemo(() => transparencyQuery.data ?? [], [transparencyQuery.data]);

const breakdownQuery = useQuery({
  queryKey: user ? queryKeys.breakdown(user.id) : ["breakdown", "anonymous"],
  queryFn: () => getBreakdown(user!.id),
  enabled: !!user && canViewScoring,
});
const breakdown = breakdownQuery.data ?? null;

const burdenShareQuery = useQuery({
  queryKey: user ? queryKeys.burdenShare(user.id) : ["burdenShare", "anonymous"],
  queryFn: () => getBurdenShare(user!.id),
  enabled: !!user && canViewScoring,
});

const burdenShareBreakdownQuery = useQuery({
  queryKey: user ? queryKeys.burdenShareBreakdown(user.id) : ["burdenShareBreakdown", "anonymous"],
  queryFn: () => getBurdenShareBreakdown(user!.id),
  enabled: !!user && canViewScoring,
});

const hasScoreLoadError =
  canViewScoring &&
  (transparencyQuery.isError ||
    breakdownQuery.isError ||
    burdenShareQuery.isError ||
    burdenShareBreakdownQuery.isError);
```

Update the banner at lines 467-471 to only ever render for the genuine-error case (permission-denied now never reaches it, since the queries don't run):

```tsx
{hasScoreLoadError && (
  <p role="alert" className="text-sm text-red-600 dark:text-red-400">
    {t("home.score_load_error")}
  </p>
)}
```

No visible "permission denied" banner is needed — per the bug report the fix is to *not surface an error at all* for a user who's known in advance to lack permission, matching how `DutyHistoryWidget`'s `canViewTransparency` prop already silently hides the whole section elsewhere in this same file.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- HomePage.test.tsx`
Expected: PASS

- [ ] **Step 5: Typecheck and commit**

```bash
npm run typecheck
git add frontend/src/pages/HomePage.tsx frontend/src/pages/HomePage.test.tsx
git commit -m "fix: skip scoring fetches on dashboard for soldiers without transparency permission

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: Bug-reports admin table — separate "last updated" column, sorted by it, rename "date" to "report date"

**Bug report (Hebrew):** "בטבלת bug reports לסדר לפי תאריך עדכון אחרון (ולהציג אותו כעמודה נפרדת מ'תאריך' ולשנות ל'תאריך דיווח')" — sort the bug-reports table by last-update date, show that as its own column separate from "date", and rename "date" to "report date".

**Root cause:** `frontend/src/pages/admin/BugReportsContent.tsx:217-306` (`bugReportColumns`) only renders a `created_at` column headed "תאריך" (line 224-229) and has no column for `updated_at`, even though `BugReportSummary.updated_at` is already fetched and typed (`frontend/src/api/bugReports.ts:33`) and already maintained server-side (`backend/app/routes/bug_reports.py:413` bumps it on every status change). There is also no default sort — check `DataTable`'s sort API before assuming one needs to be added.

**Files:**
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx:224-229` (rename column, add new column)
- Modify: `frontend/src/i18n/he.json` (add `bug_reports.reported_at` / rename existing key usage, add `bug_reports.updated_at`)
- Read (no change expected): `frontend/src/components/DataTable.tsx` — confirm the exact prop name for a default/initial sort column before Step 3
- Test: `frontend/src/pages/admin/BugReportsContent.test.tsx` (extend existing file — check with Grep first; create if absent)

**Interfaces:**
- Consumes: `BugReportSummary.updated_at: string` (already defined, `frontend/src/api/bugReports.ts:33`)
- Produces: no new exports

- [ ] **Step 1: Read `DataTable.tsx` to find the sort-control prop**

Run `Grep -n "sort" frontend/src/components/DataTable.tsx` and read the surrounding prop definitions (e.g. `defaultSortColumn` / `initialSortId` / `defaultSort`). Note the exact prop name and whether it takes a column `id` and direction — you'll need it for Step 3. If `DataTable` has no built-in default-sort prop at all, add one (a `defaultSort?: { columnId: string; direction: "asc" | "desc" }` prop that seeds the component's internal sort state instead of defaulting to insertion order) — keep the change additive/optional so no other `DataTable` caller is affected.

- [ ] **Step 2: Write the failing test**

```tsx
it("renders reported-at and updated-at as separate columns, sorted by updated-at descending by default", () => {
  const reports = [
    makeBugReport({ id: "a", created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-01T10:00:00Z" }),
    makeBugReport({ id: "b", created_at: "2026-09-02T10:00:00Z", updated_at: "2026-09-05T10:00:00Z" }),
  ];
  render(<BugReportsContent /* ...props with `reports` mocked via query */ />);

  expect(screen.getByText("תאריך דיווח")).toBeInTheDocument();
  expect(screen.getByText("עדכון אחרון")).toBeInTheDocument();

  const rows = screen.getAllByTestId(/^bug-report-row-/);
  expect(rows[0]).toHaveAttribute("data-testid", "bug-report-row-b"); // most recently updated first
});
```

Adjust to whatever row `data-testid` convention `BugReportsContent.tsx` already uses (check the table body render for an existing per-row test id before writing this — reuse it rather than inventing a new one).

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- BugReportsContent.test.tsx` (from `frontend/`)
Expected: FAIL — no "עדכון אחרון" text and no "תאריך דיווח" text yet; sort order is insertion order.

- [ ] **Step 4: Add the column and default sort**

In `frontend/src/pages/admin/BugReportsContent.tsx`, change the `created_at` column (lines 224-229) and add a new one immediately after it:

```tsx
{
  id: "created_at",
  header: t("bug_reports.reported_at"),
  cell: (report) => new Date(report.created_at).toLocaleString("he-IL"),
  sortValue: (report) => report.created_at,
},
{
  id: "updated_at",
  header: t("bug_reports.updated_at"),
  cell: (report) => new Date(report.updated_at).toLocaleString("he-IL"),
  sortValue: (report) => report.updated_at,
},
```

Add to `frontend/src/i18n/he.json` under the `bug_reports` namespace:

```json
"reported_at": "תאריך דיווח",
"updated_at": "עדכון אחרון",
```

Pass the default-sort prop discovered/added in Step 1 to the `DataTable`/table-rendering call in this file, e.g. `defaultSort={{ columnId: "updated_at", direction: "desc" }}` (use the exact prop name from Step 1).

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- BugReportsContent.test.tsx`
Expected: PASS

- [ ] **Step 6: Typecheck and commit**

```bash
npm run typecheck
git add frontend/src/pages/admin/BugReportsContent.tsx frontend/src/pages/admin/BugReportsContent.test.tsx frontend/src/i18n/he.json frontend/src/components/DataTable.tsx
git commit -m "feat: sort bug reports table by last update, split report/update date columns

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: Auto-close expired swap/exemption requests; block swap creation for past or started duties

**Bug report (Hebrew):** "כשיש החלפה פתוחה או בכללי כל בקשה פתוחה שהתאריך סיום שלה עבר, זה צריך לסגור אותה עם הערה שהתאריך עבר. עבור החלפות ספציפית זה צריך להיות גם אם התאריך התחלה עבר (אם התורנות התחילה, כלומר אם התורנות מתחילה ב-8 בערב עדיין אפשר להחליף ב-5 בערב) וגם צריך שזה ימנע ממני לפרסם בקשת החלפה על דברים בעבר או תאריכים בעבר" — any open request (swap or otherwise) whose end date has passed should auto-close with a note explaining the date passed; for swaps specifically this should also happen once the *duty has started* (not just once the calendar date turns over — a duty starting at 20:00 should still be swappable at 17:00 that same day); and creating a swap request for a past/already-started duty must be blocked outright.

**Root cause (three distinct gaps):**
1. `backend/app/services/swaps.py:1251-1285` `expire_started_swaps` compares `SwapRequest.duty_date <= today` — a **date-only** comparison. Since `duty_date` is set to `assignment.start_date` (no time component), this actually fires **too early**: a duty starting at 20:00 today has its swap request cancelled from 00:00 that day onward, which is the opposite of "can still swap at 17:00." It needs to compare against the assignment's real start (`start_date` + `start_time`, both on `DutyAssignment`, `backend/app/db/models.py:367-370`) vs. `datetime.utcnow()`.
2. There is no equivalent expiry at all for `ExemptionRequest` (`backend/app/db/models.py:744-784`, `status`/`start_date`/`end_date`) — nothing closes a stale pending exemption request whose `end_date` has passed.
3. `create_request` (`backend/app/services/swaps.py:90-171`) never checks the assignment's date/time against "now" — nothing stops creating a swap for a duty that's already over or already started.

**Files:**
- Modify: `backend/app/services/swaps.py` (`expire_started_swaps`, `create_request`)
- Modify: `backend/app/services/exemption_requests.py` (add `expire_stale_requests`, or the equivalent existing module for `ExemptionRequest` state transitions — confirm the right module with `Grep -rn "class ExemptionRequestError" backend/app/services/`)
- Modify: `backend/app/swap_expiry_worker.py` (rename/extend to also call the new exemption-request expiry, or add a second periodic call in the same loop — keep the existing 5-minute cadence)
- Test: `backend/app/services/tests/test_swaps.py`, `backend/app/services/tests/test_exemption_requests.py`

**Interfaces:**
- Consumes: `DutyAssignment.start_date: date`, `DutyAssignment.start_time: str` ("HH:MM"), `DutyAssignment.end_date`/`end_time` — already on the model
- Produces: `expire_started_swaps(session, *, now: datetime | None = None) -> int` (renamed `today` param → `now`, callers updated); new `expire_stale_exemption_requests(session, *, today: date | None = None) -> int` in the exemption-requests service; `SwapError("duty_already_started")` domain error

- [ ] **Step 1: Write the failing test for the expiry-timing fix**

Add to `backend/app/services/tests/test_swaps.py` (follow the existing fixture/factory helpers already used in that file — e.g. `create_soldier`, a duty-assignment factory — check the top of the file for the exact helper names before writing this):

```python
def test_expire_started_swaps_keeps_swap_open_before_duty_start_time(session):
    soldier = create_soldier(session, personal_number="swapexp001")
    assignment = create_duty_assignment(
        session, soldier_id=soldier.id, start_date=date.today(), end_date=date.today(),
        start_time="20:00", end_time="23:59",
    )
    req = create_request(
        session, requesting_soldier_id=soldier.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason=None, open_to_marketplace=True,
    )
    session.commit()

    count = expire_started_swaps(session, now=datetime.combine(date.today(), time(17, 0)))

    session.refresh(req)
    assert count == 0
    assert req.status == "open"


def test_expire_started_swaps_cancels_once_duty_start_time_passes(session):
    soldier = create_soldier(session, personal_number="swapexp002")
    assignment = create_duty_assignment(
        session, soldier_id=soldier.id, start_date=date.today(), end_date=date.today(),
        start_time="20:00", end_time="23:59",
    )
    req = create_request(
        session, requesting_soldier_id=soldier.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason=None, open_to_marketplace=True,
    )
    session.commit()

    count = expire_started_swaps(session, now=datetime.combine(date.today(), time(20, 1)))

    session.refresh(req)
    assert count == 1
    assert req.status == "cancelled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_swaps.py -k expire_started_swaps -v`
Expected: FAIL — `expire_started_swaps` doesn't accept a `now` kwarg yet, and the date-only comparison would cancel the "17:00, duty starts 20:00" case immediately.

- [ ] **Step 3: Fix `expire_started_swaps` to compare full start datetime**

In `backend/app/services/swaps.py`, replace the `expire_started_swaps` signature and query (lines 1251-1259):

```python
def expire_started_swaps(session: Session, *, now: datetime | None = None) -> int:
    """Cancel every open SwapRequest whose duty has actually started (start_date +
    start_time <= now) — once a duty is underway there's no one left to swap it
    with. Compares the full start datetime, not just the calendar date, so a duty
    starting at 20:00 today stays swappable earlier that same day. Returns the
    count cancelled. Called periodically by the background worker (see
    app/swap_expiry_worker.py); there is no user actor for this system action, so
    notifications/audit use actor_id=None."""
    now = now or datetime.utcnow()
    candidates = session.execute(
        select(SwapRequest, DutyAssignment)
        .join(DutyAssignment, DutyAssignment.id == SwapRequest.duty_assignment_id)
        .where(SwapRequest.status == "open", DutyAssignment.start_date <= now.date())
    ).all()
    requests = [
        req for req, assignment in candidates
        if datetime.combine(assignment.start_date, _parse_hhmm(assignment.start_time)) <= now
    ]
```

Add a small private helper near the top of the "swap expiry" section of the file:

```python
def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
```

(`time` and `datetime` are already imported in this file per the existing `datetime.utcnow()` call at the old line 1269 — confirm with `Grep -n "^from datetime" backend/app/services/swaps.py` and add `time` to that import if it's missing.)

Keep the rest of the function body (cancelling candidates, notifying recipients, writing the audit row) unchanged below this point — it already iterates `requests`.

Update the one caller, `backend/app/swap_expiry_worker.py:16`, to keep passing no explicit argument (`expire_started_swaps(session)` still works since `now` defaults to `datetime.utcnow()`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_swaps.py -k expire_started_swaps -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for blocking swap creation on past/started duties**

Add to `backend/app/services/tests/test_swaps.py`:

```python
def test_create_request_rejects_duty_already_started():
    soldier = create_soldier(session, personal_number="swapexp003")
    assignment = create_duty_assignment(
        session, soldier_id=soldier.id, start_date=date.today(), end_date=date.today(),
        start_time="00:00", end_time="23:59",
    )
    with pytest.raises(SwapError, match="duty_already_started"):
        create_request(
            session, requesting_soldier_id=soldier.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, reason=None, open_to_marketplace=True,
            now=datetime.combine(date.today(), time(12, 0)),
        )
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_swaps.py -k duty_already_started -v`
Expected: FAIL — `create_request` doesn't take a `now` kwarg and never raises this error.

- [ ] **Step 7: Add the past/started-duty check to `create_request`**

In `backend/app/services/swaps.py`, add a `now: datetime | None = None` parameter to `create_request` (line 90-99) and a check right after the `assignment.status not in (...)` check (after line 120):

```python
def create_request(
    session: Session,
    *,
    requesting_soldier_id: uuid.UUID,
    duty_assignment_id: uuid.UUID,
    target_soldier_id: uuid.UUID | None,
    reason: str | None,
    target_soldier_ids: list[uuid.UUID] | None = None,
    open_to_marketplace: bool = False,
    actor_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> SwapRequest:
    ...
    if assignment.status not in ("published", "algorithm_draft"):
        raise SwapError("not_published")
    now = now or datetime.utcnow()
    duty_start = datetime.combine(assignment.start_date, _parse_hhmm(assignment.start_time))
    if duty_start <= now:
        raise SwapError("duty_already_started")
```

Update `backend/app/routes/swaps.py:467` (`create()`) — no change needed there if it doesn't already pass `now`; it will pick up the default. Add `duty_already_started` to the frontend's `errors.*` i18n namespace (Task 5 will wire `translateApiError` generally, but add this one specific key now so the new backend error is human-readable immediately):

```json
"duty_already_started": "לא ניתן לפרסם בקשת החלפה על תורנות שכבר התחילה או הסתיימה"
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_swaps.py -k duty_already_started -v`
Expected: PASS

- [ ] **Step 9: Write the failing test for exemption-request expiry**

First check the exact status values and helper module for `ExemptionRequest` transitions: `Grep -n "status ==" backend/app/services/exemption_requests.py` — you already know from Task exploration that request statuses include `pending_commander` / `pending_duty_manager` (not a bare `"pending"`); use whatever the file's own constants/checks are. Add to `backend/app/services/tests/test_exemption_requests.py`:

```python
def test_expire_stale_exemption_requests_closes_and_notifies(session):
    soldier = create_soldier(session, personal_number="exreqexp001")
    exemption_type = create_exemption_type(session)  # use the existing factory in this test file
    req = submit_request(
        session, soldier_id=soldier.id, exemption_type_id=exemption_type.id,
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 5), reason="x",
    )
    session.commit()

    count = expire_stale_exemption_requests(session, today=date(2026, 1, 10))

    session.refresh(req)
    assert count == 1
    assert req.status == "expired"
    assert req.decision_note == "התאריך שהוגדר לבקשה עבר"
```

Adjust the factory/helper names to whatever `test_exemption_requests.py` already defines — read the top of that file before writing this step for real (do not guess a function that doesn't exist).

- [ ] **Step 10: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_exemption_requests.py -k expire_stale -v`
Expected: FAIL — `expire_stale_exemption_requests` does not exist yet.

- [ ] **Step 11: Implement `expire_stale_exemption_requests`**

In `backend/app/services/exemption_requests.py`, add (near the other status-transition functions such as `approve_commander_step`):

```python
def expire_stale_exemption_requests(session: Session, *, today: date | None = None) -> int:
    """Close every still-open ExemptionRequest whose requested end_date has
    passed, with a note explaining why — mirrors expire_started_swaps for
    swap requests (see app/services/swaps.py). Called by the same periodic
    worker; no user actor, so notifications/audit use actor_id=None."""
    today = today or date.today()
    requests = session.execute(
        select(ExemptionRequest).where(
            ExemptionRequest.status.in_(["pending_commander", "pending_duty_manager"]),
            ExemptionRequest.end_date.is_not(None),
            ExemptionRequest.end_date < today,
        )
    ).scalars().all()
    for req in requests:
        req.status = "expired"
        req.decision_note = "התאריך שהוגדר לבקשה עבר"
        create_notification(
            session, soldier_id=req.soldier_id, type=NotificationType.exemption_rejected,
            title="בקשת הפטור נסגרה — התאריך עבר", reference_type="exemption_request",
            reference_id=req.id, actor_id=None,
        )
    session.flush()
    return len(requests)
```

Add the necessary imports (`create_notification`, `NotificationType` from `app.services.notifications` / `app.db.models`) at the top of the file if not already present. Wire it into `backend/app/swap_expiry_worker.py` so both expiries run on the same 5-minute cadence:

```python
def _expire_stale_requests() -> None:
    with session_scope() as session:
        swap_count = expire_started_swaps(session)
        exemption_count = expire_stale_exemption_requests(session)
        if swap_count or exemption_count:
            session.commit()
            logger.info(
                "expiry worker: cancelled %d swap request(s), expired %d exemption request(s)",
                swap_count, exemption_count,
            )


async def run_swap_expiry_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_expire_stale_requests)
        except Exception:
            logger.warning("expiry worker: unhandled error", exc_info=True)
```

(Rename `_expire_started_swaps` → `_expire_stale_requests` and update the one import line accordingly.)

- [ ] **Step 12: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_exemption_requests.py -k expire_stale -v`
Expected: PASS

- [ ] **Step 13: Run the full targeted suite and commit**

```bash
pytest -m "duty or misc" -q
git add backend/app/services/swaps.py backend/app/services/exemption_requests.py backend/app/swap_expiry_worker.py backend/app/services/tests/test_swaps.py backend/app/services/tests/test_exemption_requests.py frontend/src/i18n/he.json
git commit -m "fix: expire swaps/exemption requests by real start time, block swaps on started duties

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: Swap confirmation UI — requester's own column reads "את/ה"

**Bug report (Hebrew):** "בדף הצגת בקשות החלפה כתוב אישור מחליף ואישור מבקש. צריך שבאישור מחליף יוצג גם השם והלינק לחייל ואישור מבקש צריך להיות את/ה" — the swap-request display shows "confirm replacer" / "confirm requester"; the replacer side needs the soldier's name and a link shown, and the requester side (which is always the current viewer, on the "my requests" view) should read "את/ה" (you).

**Root cause:** In the "my open requests" view (`frontend/src/pages/SwapsPage.tsx`'s `PendingApprovalCard`, lines 36-40, and the equivalent `MySwapCard.tsx:175-181`), the *candidate* ("מחליף") column already passes the candidate's real name + is already clickable (`candidateColumn(...)`'s `soldierId` renders as a `openSoldierModal(...)` button in `SwapApprovalColumns.tsx:118-124` for every caller) — so the name+link requirement is already met there. The actual gap is the *requester* ("מבקש") column: since this view only ever shows the viewer's own requests, its header should read "את/ה" instead of the viewer's own name (`SwapsPage.tsx:38`, `swap.requesting_soldier_name ?? t("swaps.requester")`) or the unrelated generic label currently used in `MySwapCard.tsx:178` (`t("swaps.mine")`, which is actually the tab heading text "הבקשות שלי" — not appropriate as a per-request label).

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx:38` (`PendingApprovalCard`'s `requesterColumn` call)
- Modify: `frontend/src/components/MySwapCard.tsx:178` (`requesterColumn` call)
- Modify: `frontend/src/i18n/he.json` (add `swaps.you`)
- Test: `frontend/src/components/MySwapCard.test.tsx` (extend if it exists — check with Grep; else add to `SwapsPage.test.tsx`)

**Interfaces:**
- Consumes: `requesterColumn(swap, requireDutyManagerApproval, label, t)` (unchanged signature, `frontend/src/components/SwapApprovalColumns.tsx:69`)
- Produces: no new exports

- [ ] **Step 1: Write the failing test**

```tsx
it("labels the requester's own column 'את/ה' in the my-requests view", () => {
  render(<MySwapCard swap={makeSwap({ requesting_soldier_id: currentUser.id, requesting_soldier_name: "דני כהן" })} /* ...other required props */ />);
  expect(screen.getByRole("button", { name: "את/ה" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "דני כהן" })).not.toBeInTheDocument();
});
```

Adjust to whatever `MySwapCard` test scaffolding/props already exist in the codebase (check `MySwapCard.tsx`'s prop type and any existing test file before writing this for real).

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- MySwapCard.test.tsx`
Expected: FAIL — the button currently reads "הבקשות שלי", not "את/ה".

- [ ] **Step 3: Add the `swaps.you` key and use it**

Add to `frontend/src/i18n/he.json` under `swaps`:

```json
"you": "את/ה",
```

In `frontend/src/components/MySwapCard.tsx:178`, replace:

```tsx
gateManagerFields(requesterColumn(swap, requireDutyManagerApproval, t("swaps.mine"), t), requireManagerApproval),
```

with:

```tsx
gateManagerFields(requesterColumn(swap, requireDutyManagerApproval, t("swaps.you"), t), requireManagerApproval),
```

In `frontend/src/pages/SwapsPage.tsx:38` (inside `PendingApprovalCard`, which is only ever rendered for the current user's own requests), replace:

```tsx
gateManagerFields(requesterColumn(swap, requireDutyManagerApproval, swap.requesting_soldier_name ?? t("swaps.requester"), t), requireManagerApproval),
```

with:

```tsx
gateManagerFields(requesterColumn(swap, requireDutyManagerApproval, t("swaps.you"), t), requireManagerApproval),
```

Do **not** change `SwapsPage.tsx:246` (`renderIncomingCard`'s `requesterColumn` call) or the `ApprovalsPage.tsx` call sites — those views show *other people's* requests to a commander/duty-manager or to the candidate being asked to cover, where the requester is never the viewer, so the real name must stay.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- MySwapCard.test.tsx`
Expected: PASS

- [ ] **Step 5: Typecheck and commit**

```bash
npm run typecheck
git add frontend/src/components/MySwapCard.tsx frontend/src/pages/SwapsPage.tsx frontend/src/i18n/he.json frontend/src/components/MySwapCard.test.tsx
git commit -m "fix: label the viewer's own swap-request column 'את/ה' instead of their name

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: Replace generic "שגיאה" fallbacks with the real backend error detail

**Bug report (Hebrew):** "בכל מיני מקומות מופיעה 'שגיאה' כללית במקום שגיאה עם פירוט של מה גרם לשגיאה, תעשה מעבר ותוודא שיש פירוט נורמלי לכל שגיאה" — go through the app and make sure every error shows real detail instead of a bare "error".

**Root cause:** `frontend/src/utils/translateApiError.ts` already does the right thing (maps a backend `detail` code through `errors.<code>`, falling back to a generic string only for truly unmapped codes) — but several call sites in `frontend/src/pages/admin/BugReportsContent.tsx` bypass it or hardcode a fallback that swallows real detail:
- `:122` `"שגיאה בעדכון הסטטוס"`, `:136` `"שגיאה בטעינת צילום המסך"`, `:161` `"שגיאה בייבוא הקבצים"`, `:212` `"שגיאה בטעינת ה-JSON"` — all pass a hardcoded Hebrew string as the *fallback* to `translateApiError`, which is fine as a fallback *if* the code is genuinely unmapped, but none of these add the corresponding `errors.<code>` keys, so mapped backend codes never get a real translation and always fall through to the generic string.
- `:338` `r.detail ?? "שגיאה"` drops the real per-file import error entirely instead of running it through `translateApiError`.
- `:399-401` (`query.isError` render) shows a hardcoded `"שגיאה בטעינת הדיווחים"` with no access to `query.error` at all.

**Files:**
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx` (lines ~122, 136, 161, 212, 338, 399-401)
- Modify: `frontend/src/i18n/he.json` (add any missing `errors.*` keys discovered while doing this)
- Test: `frontend/src/pages/admin/BugReportsContent.test.tsx`

**Interfaces:**
- Consumes: `translateApiError(err: unknown, t: TFn, fallback?: string): string` (existing, `frontend/src/utils/translateApiError.ts:41`)
- Produces: no new exports

- [ ] **Step 1: Identify the actual backend error codes for each call site**

For each of the five call sites, find the backend route it calls and read the `detail=` values it can raise (e.g. status update → `PATCH /api/admin/bug-reports/{id}` in `backend/app/routes/bug_reports.py`; screenshot fetch, JSON import, JSON fetch — same file). List the concrete codes (e.g. `not_found`, `invalid_status`, `file_too_large`) so Step 2's i18n keys are real, not guesses.

- [ ] **Step 2: Write the failing test for the query-level error (the clearest case)**

```tsx
it("shows the real backend error detail when the bug reports query fails, not a generic message", async () => {
  server.use(
    rest.get("/api/admin/bug-reports", (req, res, ctx) =>
      res(ctx.status(403), ctx.json({ detail: "not_admin" }))),
  );
  render(<BugReportsContent />);
  expect(await screen.findByText("אין לך הרשאה לצפות בדיווחים")).toBeInTheDocument();
  expect(screen.queryByText("שגיאה בטעינת הדיווחים")).not.toBeInTheDocument();
});
```

Adjust the mock-server setup to whatever the existing test file already uses (MSW, `vi.mock` on the api module, etc. — check `BugReportsContent.test.tsx` or a sibling admin page test for the established pattern before writing this).

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- BugReportsContent.test.tsx`
Expected: FAIL — the hardcoded `"שגיאה בטעינת הדיווחים"` string renders regardless of `query.error`.

- [ ] **Step 4: Fix each call site**

At line ~399-401, replace the hardcoded render with:

```tsx
{query.isError && (
  <p className="text-red-600 text-sm" role="alert">
    {translateApiError(query.error, t, "שגיאה בטעינת הדיווחים")}
  </p>
)}
```

At line 338, replace `r.detail ?? "שגיאה"` with `translateApiError(r, t, "שגיאה בייבוא הקובץ")` if `r` is an axios-error-shaped object, or, if `r` is already the parsed per-file result (not a raw error), route its `detail` string through the same `errors.<code>` map by extracting the small piece of `translateApiError` that maps a code to text — check the actual shape of `r` at this line before choosing; do not guess blindly, read the surrounding function first.

For lines 122, 136, 161, 212: keep the existing `translateApiError(err, t, "<hardcoded fallback>")` calls as the *fallback* (that part was already correct), and add the real `errors.<code>` keys found in Step 1 to `frontend/src/i18n/he.json` so mapped codes stop falling through to the generic fallback text. Example, if the status-update endpoint can return `detail="invalid_status_transition"`:

```json
"errors": {
  "invalid_status_transition": "לא ניתן לעבור לסטטוס הזה ממצב הדיווח הנוכחי"
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- BugReportsContent.test.tsx`
Expected: PASS

- [ ] **Step 6: Sweep for the same anti-pattern elsewhere**

Run `Grep -rn '"שגיאה"' frontend/src --glob '*.tsx'` and `Grep -rn "?? \"שגיאה" frontend/src --glob '*.tsx'` to find other call sites that drop `err`/`detail` entirely (not just the ones already identified in `BugReportsContent.tsx`). For each hit found outside `BugReportsContent.tsx`, apply the same fix: route the real error object through `translateApiError(err, t, fallback)` instead of a bare literal. Do this for every hit — do not stop at the first file.

- [ ] **Step 7: Run the full frontend test suite and commit**

```bash
npm test
npm run typecheck
git add frontend/src/pages/admin/BugReportsContent.tsx frontend/src/i18n/he.json frontend/src/pages/admin/BugReportsContent.test.tsx
git commit -m "fix: surface real backend error detail instead of generic 'שגיאה' text

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

(If Step 6 touched additional files, add and mention them in the same commit — this is one cohesive sweep, not several unrelated changes.)

---

## Task 6: Require a reason before granting an exemption

**Bug report (Hebrew):** "כשנותנים פטור למישהו אבל לא נותנים סיבה זה כותב שגיאה בלי פירוט, וגם זה צריך לא לתת ללחוץ על הכפתור אם אין סיבה כתובה" — granting an exemption without a reason shows an undetailed error, and the button shouldn't be clickable at all when no reason is written.

**Root cause:** Two separate exemption-grant UIs, both incomplete:
1. `frontend/src/components/EntriesExitsPanel.tsx` (`handleGrantExemption`, lines 53-65, and its modal, lines 100-123) has **no reason field at all** — it calls `grantExemption()` without a `reason`.
2. `frontend/src/components/ExemptionsPanel.tsx` has a reason textarea (`commanderReason`, lines 572-578) but the submit button's `disabled` (line 627) doesn't include it — emptiness is only checked inside the click handler (`openCommanderConfirm`, lines 219-239), so the button is clickable and only shows an inline error after the click.
3. Backend `GrantRequest` (`backend/app/routes/exemptions.py:60-65`) declares `reason: str | None = Field(default=None, max_length=1000)` — optional, so a request with no reason succeeds silently (`ex.reason = None`) instead of failing with a clear 400. Contrast `GrantCommanderExemptionRequest` (lines 217-221), which already correctly requires `min_length=1`.

**Files:**
- Modify: `frontend/src/components/EntriesExitsPanel.tsx` (add reason state + textarea + disabled condition)
- Modify: `frontend/src/components/ExemptionsPanel.tsx:627` (extend `disabled`)
- Modify: `backend/app/routes/exemptions.py:64` (`GrantRequest.reason`)
- Test: `backend/app/routes/tests/test_exemptions.py` (create — no existing route-level test file for this router; follow the fixture pattern from `backend/app/routes/tests/test_bug_reports.py`)
- Test: `frontend/src/components/EntriesExitsPanel.test.tsx`, `frontend/src/components/ExemptionsPanel.test.tsx` (extend if they exist, else create)

**Interfaces:**
- Consumes: `grantExemption(soldierId, { exemption_type_id, is_medical?, start_date, end_date?, reason? })` (`frontend/src/api/exemptions.ts:44`) — becomes effectively required at the type level too
- Produces: `GrantRequest.reason: str` (now required, `min_length=1`)

- [ ] **Step 1: Write the failing backend test**

Create `backend/app/routes/tests/test_exemptions.py`:

```python
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_grant_exemption_requires_a_reason(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="exgrant001", role="admin")
    target = create_soldier(admin_session, personal_number="exgrant002")
    from app.db.models import ExemptionType
    exemption_type = ExemptionType(name="חופשה")
    admin_session.add(exemption_type)
    admin_session.commit()

    resp = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        json={"exemption_type_id": str(exemption_type.id), "start_date": str(date.today())},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any(err["loc"][-1] == "reason" for err in detail)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/routes/tests/test_exemptions.py -v`
Expected: FAIL — currently returns 200/201 since `reason` is optional.

- [ ] **Step 3: Make `reason` required on the backend**

In `backend/app/routes/exemptions.py:60-65`, change:

```python
class GrantRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    reason: str = Field(min_length=1, max_length=1000)
    is_medical: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/routes/tests/test_exemptions.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing frontend test for `EntriesExitsPanel`**

```tsx
it("disables the exempt-confirm button until a reason is entered", () => {
  render(<EntriesExitsPanel /* required props */ />);
  fireEvent.click(screen.getByText("פטור")); // opens the modal for a soldier row
  const confirmButton = screen.getByRole("button", { name: "פטור" }); // the modal's confirm button, same label per existing code
  expect(confirmButton).toBeDisabled();
  fireEvent.change(screen.getByTestId("exempt-reason"), { target: { value: "מחלה" } });
  expect(confirmButton).not.toBeDisabled();
});
```

Adjust to the file's actual test setup/props (check for an existing `EntriesExitsPanel.test.tsx` first and follow its render helper).

- [ ] **Step 6: Run test to verify it fails**

Run: `npm test -- EntriesExitsPanel.test.tsx`
Expected: FAIL — there's no reason field/testid yet, and the button isn't gated on one.

- [ ] **Step 7: Add the reason field to `EntriesExitsPanel`**

In `frontend/src/components/EntriesExitsPanel.tsx`, add state near the other `exempt*` state (find the `useState` block containing `exemptTarget`/`exemptionTypeId`/`exemptStart`/`exemptEnd`):

```tsx
const [exemptReason, setExemptReason] = useState("");
```

Update `handleGrantExemption` (lines 53-65):

```tsx
async function handleGrantExemption() {
  if (!exemptTarget || !exemptionTypeId || !exemptStart || !isDateRangeValid(exemptStart, exemptEnd) || !exemptReason.trim()) return;
  await grantExemption(exemptTarget.id, {
    exemption_type_id: exemptionTypeId,
    start_date: exemptStart,
    end_date: exemptEnd || null,
    reason: exemptReason.trim(),
  });
  setExemptTarget(null);
  setExemptionTypeId("");
  setExemptStart("");
  setExemptEnd("");
  setExemptReason("");
  onRefresh();
}
```

Add the textarea to the modal (after the "exemption_end" `DateInput` block, before the button row, around line 115):

```tsx
<label className="block text-sm">{t("command_dashboard.exemption_reason")}</label>
<textarea
  value={exemptReason}
  onChange={(e) => setExemptReason(e.target.value)}
  className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
  data-testid="exempt-reason"
/>
```

Update the confirm button's `disabled` (line 118):

```tsx
<button onClick={handleGrantExemption} disabled={!isDateRangeValid(exemptStart, exemptEnd) || !exemptReason.trim()} className="px-3 py-1 bg-indigo-600 text-white rounded text-sm disabled:opacity-50">{t("command_dashboard.exempt")}</button>
```

Also reset `exemptReason` wherever `exemptTarget` is cleared elsewhere in the file (e.g. the modal's cancel button / backdrop click) — grep the file for `setExemptTarget(null)` and add `setExemptReason("")` alongside every occurrence.

Add the i18n key to `frontend/src/i18n/he.json` under `command_dashboard`:

```json
"exemption_reason": "סיבה",
```

- [ ] **Step 8: Run test to verify it passes**

Run: `npm test -- EntriesExitsPanel.test.tsx`
Expected: PASS

- [ ] **Step 9: Write the failing frontend test for `ExemptionsPanel`**

```tsx
it("disables the commander exemption submit button until a reason is entered", () => {
  render(<ExemptionsPanel /* required props */ />);
  // navigate to the state where the commander-grant textarea/button are visible, per the component's existing flow
  const submitButton = screen.getByTestId("commander-exemption-submit");
  expect(submitButton).toBeDisabled();
  fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה כלשהי" } });
  expect(submitButton).not.toBeDisabled();
});
```

- [ ] **Step 10: Run test to verify it fails**

Run: `npm test -- ExemptionsPanel.test.tsx`
Expected: FAIL — the button is only gated on `commanderTypeId`/`start`/date-range, not `commanderReason`.

- [ ] **Step 11: Gate the `ExemptionsPanel` button on the reason**

In `frontend/src/components/ExemptionsPanel.tsx:627`, change:

```tsx
disabled={!commanderTypeId || !start || !isDateRangeValid(start, end)}
```

to:

```tsx
disabled={!commanderTypeId || !start || !isDateRangeValid(start, end) || !commanderReason.trim()}
```

The existing inline error path in `openCommanderConfirm` (lines 219-239, specifically 225-228) can stay as a defensive check — it's now unreachable via the disabled button but harmless to leave, since `openCommanderConfirm` may still be reachable via keyboard submit on the textarea in some browsers.

- [ ] **Step 12: Run test to verify it passes**

Run: `npm test -- ExemptionsPanel.test.tsx`
Expected: PASS

- [ ] **Step 13: Run full targeted suites and commit**

```bash
pytest -m soldiers -q
npm run typecheck
git add backend/app/routes/exemptions.py backend/app/routes/tests/test_exemptions.py frontend/src/components/EntriesExitsPanel.tsx frontend/src/components/ExemptionsPanel.tsx frontend/src/i18n/he.json frontend/src/components/EntriesExitsPanel.test.tsx frontend/src/components/ExemptionsPanel.test.tsx
git commit -m "fix: require a reason to grant an exemption, disable submit until one is entered

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Duty managers must not approve the commander-approval stage unless they actually command that soldier

**Bug report (Hebrew):** "אחראי תורנויות יכול לאשר את שלב המפקד לפטורים (ואולי לעוד דברים), תוודא שזה לא נכון, אלא אם האחראי תורנויות הוא גם מפקד של אותו חייל" — a duty officer can approve the commander stage for exemptions (and maybe other things); make sure that's not allowed unless the duty officer is also that soldier's commander.

**Root cause:** The exact same buggy fallback pattern is duplicated in three places. Each one first correctly checks `senior_commander_approval_authorized` (which properly verifies the user actually commands a node at or above the required level over the target — `backend/app/services/authority.py:125-134`, scoped via `_commanded_node_ids_only`, i.e. commander relationships only, no duty-manager scope). But each then falls back to also allowing *any* duty manager whose **duty-manager scope** (not commander relationship) merely covers the target node:

1. `backend/app/routes/exemption_requests.py:521-523` (`approve_exemption_request_commander_step`)
2. `backend/app/services/approval_scope.py:246-251` (`exemption_approval_flags`, the `can_commander_step` mirror used to decide whether to show the approve button/route a notification)
3. `backend/app/routes/constraints.py:545-547` (`approve`, the `c.status in ("pending", "pending_commander")` branch)

The `approval_scope.py` docstring (lines 225-230) documents this as *intentional*, reasoning that `CONSTRAINT_APPROVE` is in both `_DM_ACTIONS` and `_COMMANDER_ACTIONS` in `authz.py`'s `can()` — but that's exactly the bug: it conflates "this action is duty-manager-approvable in general" with "this specific *commander* stage of a two-stage approval is duty-manager-approvable," which the report says should never be true unless the duty manager is also the commander.

**Files:**
- Modify: `backend/app/routes/exemption_requests.py:521-523`
- Modify: `backend/app/services/approval_scope.py:246-251` (and its docstring, lines 218-230)
- Modify: `backend/app/routes/constraints.py:544-547`
- Test: `backend/app/services/tests/test_exemption_requests.py`, `backend/app/services/tests/test_constraints.py`

**Interfaces:**
- Consumes: `senior_commander_approval_authorized(session, *, user, target_node) -> bool` (unchanged, `backend/app/services/authority.py:125`)
- Produces: no new exports — the fix removes a branch, it doesn't add one

- [ ] **Step 1: Write the failing test for the exemption commander-step route**

Add to `backend/app/services/tests/test_exemption_requests.py` (or a new route-level test file `backend/app/routes/tests/test_exemption_requests_authz.py` if the existing file is service-layer-only — check its imports first: if it imports `fastapi.testclient.TestClient`, extend it in place; otherwise create the new route-level file following the `test_bug_reports.py` pattern):

```python
def test_duty_manager_without_commander_relationship_cannot_approve_commander_step(client: TestClient, admin_session: Session):
    from app.db.models import DutyManagerScope, ExemptionRequest, ExemptionType, HierarchyNode

    root = admin_session.query(HierarchyNode).filter_by(parent_id=None).first()
    target = create_soldier(admin_session, personal_number="rbacbug001", hierarchy_node_id=root.id)
    duty_manager = create_soldier(admin_session, personal_number="rbacbug002")
    admin_session.add(DutyManagerScope(soldier_id=duty_manager.id, hierarchy_node_id=root.id))
    exemption_type = ExemptionType(name="בדיקה")
    admin_session.add(exemption_type)
    admin_session.flush()
    req = ExemptionRequest(
        soldier_id=target.id, exemption_type_id=exemption_type.id,
        status="pending_commander",
    )
    admin_session.add(req)
    admin_session.commit()

    resp = client.post(
        f"/api/exemption-requests/{req.id}/approve-commander",
        json={"decision_note": None},
        headers=auth_headers(duty_manager),
    )
    assert resp.status_code == 403
```

Adjust field/constructor names (`DutyManagerScope`, `ExemptionRequest`) to whatever `backend/app/db/models.py` actually requires — re-check the model definitions read earlier in this plan (`ExemptionRequest`, lines 744-784) for required vs. optional fields before finalizing this test.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_exemption_requests.py -k commander_relationship -v`
Expected: FAIL — currently returns 200 because the duty-manager fallback grants approval.

- [ ] **Step 3: Remove the duty-manager fallback from the exemption commander-step route**

In `backend/app/routes/exemption_requests.py:521-523`, change:

```python
if not senior_commander_approval_authorized(session, user=user, target_node=target_node):
    if not (is_duty_manager(session, user.id) and can(user, Action.CONSTRAINT_APPROVE, target_node=target_node, roots=scope_root_ids(session, user), is_commander=is_commander(session, user.id), is_duty_manager=True)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

to:

```python
if not senior_commander_approval_authorized(session, user=user, target_node=target_node):
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

Remove the now-unused `is_duty_manager`, `can`, `scope_root_ids`, `is_commander` imports from this file **only if** nothing else in the file still uses them — check with `Grep -n "is_duty_manager\|scope_root_ids\|Action.CONSTRAINT_APPROVE" backend/app/routes/exemption_requests.py` first, since this pattern is duplicated later in the same file (per the exploration notes, "around lines 820-822") — that second occurrence needs the identical fix in this same step, and the imports stay if that call site (or the duty-manager-step route elsewhere in the file) still needs them.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_exemption_requests.py -k commander_relationship -v`
Expected: PASS

- [ ] **Step 5: Apply the identical fix to `approval_scope.py`**

In `backend/app/services/approval_scope.py`, change `exemption_approval_flags` (lines 246-251):

```python
can_commander_step = senior_commander_approval_authorized(
    session, user=viewer, target_node=target_node,
)
```

Update the docstring (lines 218-230) to remove the now-incorrect claim that an in-scope duty manager can also approve the commander step — replace it with a note that this mirrors the route's `senior_commander_approval_authorized`-only check, and that duty-manager approval only ever applies to `can_dm_step`. Remove the now-unused `can`, `Action` import from the local `from app.auth.authz import ...` inside the function if `viewer_is_duty_manager`/`is_duty_manager` are still needed for `can_dm_step` (they are — keep those, drop only what's actually unused after this edit).

Add a corresponding test to whatever test file already covers `approval_scope.py` (`Grep -rln "exemption_approval_flags" backend/app/services/tests/` to find it — extend that file rather than creating a new one) asserting `exemption_approval_flags` now returns `can_commander_step=False` for a duty-manager-only viewer and `True` for an actual commander.

- [ ] **Step 6: Run that test to verify it passes**

Run: `pytest backend/app/services/tests -k exemption_approval_flags -v`
Expected: PASS

- [ ] **Step 7: Write the failing test for the analogous `constraints.py` bug**

Add to `backend/app/services/tests/test_constraints.py`:

```python
def test_duty_manager_without_commander_relationship_cannot_approve_constraint(client: TestClient, admin_session: Session):
    # mirror the setup from test_exemption_requests.py's commander_relationship test:
    # a duty manager whose DutyManagerScope covers the target's node, but who does
    # not command that node, must get 403 approving a "pending"/"pending_commander" constraint.
    ...
```

Fill in the actual `PersonalConstraint` creation using whatever factory this test file already has (check the top of `test_constraints.py` for the existing constraint-creation helper before writing this for real).

- [ ] **Step 8: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_constraints.py -k commander_relationship -v`
Expected: FAIL

- [ ] **Step 9: Apply the identical fix to `constraints.py`**

In `backend/app/routes/constraints.py:544-547`, change:

```python
if c.status in ("pending", "pending_commander"):
    if not senior_commander_approval_authorized(session, user=user, target_node=target_node):
        if not (is_duty_manager(session, user.id) and can(user, Action.CONSTRAINT_APPROVE, target_node=target_node, roots=scope_root_ids(session, user), is_commander=is_commander(session, user.id), is_duty_manager=True)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
else:
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
```

to:

```python
if c.status in ("pending", "pending_commander"):
    if not senior_commander_approval_authorized(session, user=user, target_node=target_node):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
else:
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
```

The `else` branch (duty-manager-only step for non-commander statuses) is untouched — it's a legitimately different, single-stage approval, not the commander stage, so `authorize(..., CONSTRAINT_APPROVE)` granting duty managers access there is correct and out of scope for this bug.

- [ ] **Step 10: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_constraints.py -k commander_relationship -v`
Expected: PASS

- [ ] **Step 11: Run the full auth-adjacent suite and commit**

```bash
pytest -m "duty or hierarchy" -q
git add backend/app/routes/exemption_requests.py backend/app/services/approval_scope.py backend/app/routes/constraints.py backend/app/services/tests/test_exemption_requests.py backend/app/services/tests/test_constraints.py
git commit -m "fix: duty managers can no longer approve the commander stage without commanding the soldier

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: Notify on-duty soldiers and their commanders when duty instructions or the contact person change

**Bug report (Hebrew):** "לשלוח עדכון לחיילים בתורנות ולמפקדים שלהם כשיש עדכון בהנחיות של התורנות או של פרטי איש קשר האחראי" — send an update to soldiers on duty and their commanders when the duty's instructions or the responsible contact person's details change.

**Root cause:** `update_duty_type` (`backend/app/services/duty_config.py:89-149`) already mutates `contact_name`, `contact_phone`, and `instructions` (lines 135-144) but never calls into the notification system — there's no `create_notification`/`notify_*` call anywhere in this function, so no one is told when these change.

**Files:**
- Modify: `backend/app/services/duty_config.py` (`update_duty_type`)
- Test: `backend/app/services/tests/test_duty_config.py`

**Interfaces:**
- Consumes: `create_notification(session, *, soldier_id, type, title, body=None, reference_type=None, reference_id=None, actor_id=None, metadata=None)` (`backend/app/services/notifications.py:341`); `NotificationType` enum (`backend/app/db/models.py:1472`)
- Produces: `NotificationType.duty_instructions_updated` (new enum member); a private `_notify_duty_instructions_changed(session, *, duty_type, actor_id) -> None` helper in `duty_config.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_duty_config.py` (follow the existing fixture/factory pattern in that file — check its top for how `DutyType` and `DutyAssignment` are constructed before writing this for real):

```python
def test_update_duty_type_notifies_on_duty_soldiers_and_their_commanders_on_instructions_change(session):
    root = create_hierarchy_node(session)  # use whatever helper this file already has
    commander = create_soldier(session, personal_number="dutynotif001", hierarchy_node_id=root.id)
    root.commander_id = commander.id
    on_duty_soldier = create_soldier(session, personal_number="dutynotif002", hierarchy_node_id=root.id)
    duty_type = create_duty_type(session, name="שמירה")
    create_duty_assignment(
        session, soldier_id=on_duty_soldier.id, duty_type_id=duty_type.id,
        start_date=date.today(), end_date=date.today() + timedelta(days=1), status="published",
    )
    session.commit()

    update_duty_type(session, duty_type=duty_type, instructions="הנחיות חדשות", name=None, score_per_day=None, description=None)
    session.commit()

    notifs = session.query(Notification).filter_by(soldier_id=on_duty_soldier.id).all()
    assert any(n.type == NotificationType.duty_instructions_updated for n in notifs)
    commander_notifs = session.query(Notification).filter_by(soldier_id=commander.id).all()
    assert any(n.type == NotificationType.duty_instructions_updated for n in commander_notifs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_duty_config.py -k notifies_on_duty -v`
Expected: FAIL — `NotificationType.duty_instructions_updated` doesn't exist yet and no notifications are sent.

- [ ] **Step 3: Add the notification type**

In `backend/app/db/models.py`, add to the `NotificationType` enum (near the other `duty`-related members, after line 1502):

```python
    duty_instructions_updated = "duty_instructions_updated"
```

This requires an Alembic migration if `NotificationType` is backed by a Postgres enum type rather than a plain `Text` column — check with `Grep -n "NotificationType" backend/app/db/models.py` around the `Notification` model's `type` column definition. If it's a native enum (`sa.Enum(NotificationType)`), create the migration:

```bash
cd backend && alembic revision -m "add duty_instructions_updated notification type"
```

and fill in the generated file's `upgrade()`/`downgrade()` with `op.execute("ALTER TYPE notificationtype ADD VALUE 'duty_instructions_updated'")` (match the exact enum type name used by existing similar migrations — search `backend/alembic/versions/` for a prior `ALTER TYPE ... ADD VALUE` migration adding a `NotificationType` member and copy its exact syntax, including how it names the Postgres enum type). If the column is plain `Text`/`String` with the Python enum only used at the ORM layer, no migration is needed — confirm before assuming either way.

- [ ] **Step 4: Implement the notification in `update_duty_type`**

In `backend/app/services/duty_config.py`, add a helper and call it when any of the three relevant fields actually change. First capture whether they changed (the function doesn't currently track before/after for these three fields — `before` at line 110-114 only tracks `name`/`score_per_day`/`description`):

```python
def update_duty_type(
    session: Session,
    *,
    duty_type: DutyType,
    name: str | None,
    score_per_day: Decimal | None,
    description: str | None,
    actor_id: uuid.UUID | None = None,
    requirements: dict | None = None,
    reserve_ratio: Decimal | None = None,
    reserve_minimum: int | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    instructions: str | None = None,
    is_external: bool | None = None,
    requires_weapon: bool | None = None,
    required_range_type: object = ...,
    eligible_node_ids: object = ...,
) -> DutyType:
    before = {
        "name": duty_type.name,
        "score_per_day": str(duty_type.score_per_day),
        "description": duty_type.description,
    }
    contact_or_instructions_changed = (
        (contact_name is not None and contact_name != duty_type.contact_name)
        or (contact_phone is not None and contact_phone != duty_type.contact_phone)
        or (instructions is not None and instructions != duty_type.instructions)
    )
    ...
    # (existing field-assignment block, unchanged)
    ...
    if contact_or_instructions_changed:
        _notify_duty_instructions_changed(session, duty_type=duty_type, actor_id=actor_id)
    return dt
```

Place the `contact_or_instructions_changed` computation before the existing `if contact_name is not None: duty_type.contact_name = contact_name` block (so it compares against the *old* value), and the `_notify_duty_instructions_changed` call at the end of the function, before whatever `return` statement already exists (check the exact end of the function — the excerpt read earlier cuts off mid-function; read the rest of `update_duty_type` before finalizing placement).

Add the helper in the same file:

```python
def _notify_duty_instructions_changed(session: Session, *, duty_type: DutyType, actor_id: uuid.UUID | None) -> None:
    """Tell every soldier with a current/future published assignment to this
    duty type, plus their direct commander, that its instructions or contact
    person changed."""
    from app.db.models import DutyAssignment, HierarchyNode, Notification, Soldier
    from app.services.notifications import create_notification, NotificationType

    today = date.today()
    soldier_ids = set(session.execute(
        select(DutyAssignment.soldier_id).where(
            DutyAssignment.duty_type_id == duty_type.id,
            DutyAssignment.status == "published",
            DutyAssignment.end_date >= today,
        )
    ).scalars().all())
    if not soldier_ids:
        return
    notified = set()
    for soldier_id in soldier_ids:
        create_notification(
            session, soldier_id=soldier_id, type=NotificationType.duty_instructions_updated,
            title=f"עודכנו ההנחיות/פרטי הקשר עבור תורנות {duty_type.name}",
            reference_type="duty_type", reference_id=duty_type.id, actor_id=actor_id,
        )
        notified.add(soldier_id)
        soldier = session.get(Soldier, soldier_id)
        commander = _direct_commander(session, soldier) if soldier else None
        if commander is not None and commander.id not in notified:
            create_notification(
                session, soldier_id=commander.id, type=NotificationType.duty_instructions_updated,
                title=f"עודכנו ההנחיות/פרטי הקשר עבור תורנות {duty_type.name} (חיילים תחת פיקודך משובצים אליה)",
                reference_type="duty_type", reference_id=duty_type.id, actor_id=actor_id,
            )
            notified.add(commander.id)


def _direct_commander(session: Session, s) -> "Soldier | None":
    """Return the soldier's direct commander from the hierarchy, skipping self.
    Mirrors app/routes/soldiers.py's private _direct_commander — duplicated
    here rather than imported since that one is route-module-private and this
    is a services-layer call site."""
    from app.db.models import HierarchyNode, Soldier

    if s.hierarchy_node_id is None:
        return None
    node = session.get(HierarchyNode, s.hierarchy_node_id)
    if node is None:
        return None
    if node.commander_id and node.commander_id != s.id:
        return session.get(Soldier, node.commander_id)
    if node.parent_id is None:
        return None
    parent = session.get(HierarchyNode, node.parent_id)
    if parent is None or parent.commander_id is None or parent.commander_id == s.id:
        return None
    return session.get(Soldier, parent.commander_id)
```

Add `from datetime import date` and `from sqlalchemy import select` to this file's imports if not already present (check the top of `duty_config.py` first).

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_duty_config.py -k notifies_on_duty -v`
Expected: PASS

- [ ] **Step 6: Run the full targeted suite, migrate if needed, and commit**

```bash
cd backend && alembic upgrade head   # only if Step 3 added a migration
pytest -m duty -q
git add backend/app/db/models.py backend/app/services/duty_config.py backend/app/services/tests/test_duty_config.py backend/alembic/versions/
git commit -m "feat: notify on-duty soldiers and their commanders when duty instructions change

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Final verification

After all 8 tasks are committed on the feature branch:

```bash
pytest -q
```
```powershell
cd frontend
npm run lint
npm run typecheck
npm test
```

Expected: all green. Then use the `merge-worktree-to-dev` project skill to integrate into `dev` (per `CLAUDE.md` — never merge directly into `master`).
