# Constraints Fixes, Partial Import, Approval Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three personal-constraint bugs (double-approve race, a duty-history privacy leak, and a quarterly-quota boundary bug + retraction), add per-section opt-in to the Excel import wizard, and surface "waiting on X" approval status to the soldier who submitted a request.

**Architecture:** Five independent changes across the existing FastAPI/SQLAlchemy backend (`backend/app/`) and React/TS frontend (`frontend/src/`). No new tables, no new API routes except one already-planned reuse of an existing generic `selections` field. Each task is independently testable and committable; they touch non-overlapping files except `constraints.py`/`constraints.ts`/`MyRequestsPage.tsx`, which are touched by more than one task (noted below).

**Tech Stack:** FastAPI, SQLAlchemy, pytest (backend); React, TypeScript, @tanstack/react-query, vitest, @testing-library/react (frontend).

## Global Constraints

- Backend tests run via `pytest -q` from `backend/` (venv already active in this repo's shell). Do not use `--slow`.
- Frontend tests run via `npm test` from `frontend/`.
- Follow existing code style exactly: this codebase mixes `t("...")` i18n calls with hardcoded Hebrew strings in the same files (e.g. `ApprovalsPage.tsx`'s `er-stage` paragraph is hardcoded). For new small UI strings introduced in this plan, use hardcoded Hebrew matching the surrounding code's own convention in each file — do not add new keys to `he.json` (a past incident found silent duplicate-key bugs there; avoid touching it unless a task explicitly says to).
- Every backend service function already in this file uses SQLAlchemy `Session`, `session.flush()`/`session.commit()` at the route layer, and raises the module's own `*Error` exception class — follow that pattern exactly, do not introduce new exception types.
- Every task ends with running the relevant test file(s) and a git commit.

---

## Task 1: Fix duty-history privacy leak (personal-constraint reason exposed regardless of viewer)

**Files:**
- Modify: `backend/app/services/duty_history.py:657-672`
- Test: `backend/app/services/tests/test_duty_history.py`

**Interfaces:**
- Consumes: `get_duty_history(session, soldier_id, include_drafts=False, include_sensitive=True)` — existing signature, unchanged.
- Produces: same `TimelineEvent` dataclass, unchanged shape. No other task depends on this one.

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_duty_history.py`, near `test_personal_constraint_appears` (around line 200):

```python
def test_personal_constraint_reason_hidden_when_not_sensitive(admin_session, soldier):
    """A viewer without private-info visibility must not see the constraint's
    reason via duty history, even though the event itself (dates, status)
    stays visible. Regression test: get_duty_history previously ignored
    include_sensitive for personal_constraint events."""
    c = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date(2026, 6, 20),
        end_date=date(2026, 6, 21),
        reason="אירוע משפחתי",
    )
    admin_session.add(c)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id, include_sensitive=False)

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "personal_constraint"
    assert ev.title == "אילוצים אישיים"
    assert ev.description is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_duty_history.py::test_personal_constraint_reason_hidden_when_not_sensitive -v`
Expected: FAIL — `ev.description` is `"אירוע משפחתי"`, not `None`.

- [ ] **Step 3: Fix the implementation**

In `backend/app/services/duty_history.py`, the `PersonalConstraint` events loop currently reads (lines 657-672):

```python
    # --- PersonalConstraint events ---
    constraints = list(
        session.execute(
            select(PersonalConstraint).where(PersonalConstraint.soldier_id == soldier_id)
        ).scalars().all()
    )
    for c in constraints:
        events.append(
            TimelineEvent(
                id=c.id,
                event_type="personal_constraint",
                date=c.start_date.isoformat(),
                end_date=_isodate(c.end_date),
                title="אילוצים אישיים",
                description=c.reason,
                status=c.status,
                metadata={
                    "decision_note": c.decision_note,
                },
                created_at=c.created_at.isoformat(),
            )
        )
```

Replace the `description=c.reason,` line and the `metadata` dict so both the reason and the decision note (also private — it's the approver's free-text note about *why*, tied to the same private request) are gated:

```python
    # --- PersonalConstraint events ---
    constraints = list(
        session.execute(
            select(PersonalConstraint).where(PersonalConstraint.soldier_id == soldier_id)
        ).scalars().all()
    )
    for c in constraints:
        events.append(
            TimelineEvent(
                id=c.id,
                event_type="personal_constraint",
                date=c.start_date.isoformat(),
                end_date=_isodate(c.end_date),
                title="אילוצים אישיים",
                description=c.reason if include_sensitive else None,
                status=c.status,
                metadata={
                    "decision_note": c.decision_note if include_sensitive else None,
                },
                created_at=c.created_at.isoformat(),
            )
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_duty_history.py -v`
Expected: PASS — all tests in the file, including the existing `test_personal_constraint_appears` (which calls `get_duty_history` with the default `include_sensitive=True` and still expects the reason to show).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/duty_history.py backend/app/services/tests/test_duty_history.py
git commit -m "fix: hide personal-constraint reason/decision-note in duty history from non-private viewers"
```

---

## Task 2: Fix quarterly quota boundary bug + widen retraction to `pending_duty_manager`

**Files:**
- Modify: `backend/app/services/constraints.py:44` (cap-check anchor), `backend/app/services/constraints.py:245-278` (`cancel_constraint` eligibility)
- Modify: `frontend/src/pages/MyRequestsPage.tsx:233-242` (cancel button condition + stale comment)
- Test: `backend/tests/unit/test_constraints_service.py`
- Test: `frontend/src/pages/MyRequestsPage.test.tsx`

**Interfaces:**
- Consumes: `remaining_days(session, *, soldier_id, today=None)` — existing signature, unchanged; only its caller changes.
- Produces: `cancel_constraint` now succeeds (returns `None`, deletes the row) for `status in ("pending_commander", "pending_duty_manager")`, still raises `ConstraintError("not_pending")` for `"approved"`/`"rejected"`/`"cancelled"`. `MyRequestsPage`'s cancel button now renders for both pending statuses.

### Part A — Backend: quota anchor fix

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_constraints_service.py`, after `test_submit_cap_check_is_period_scoped_not_full_future_span` (around line 128):

```python
def test_submit_cap_checked_against_requests_own_quarter_not_submission_day(admin_session):
    """Regression test: submit_constraint's cap check must anchor the period
    on the REQUEST's own start_date, not on the real submission-day `today`.
    Before the fix, a request submitted today for dates in a distant future
    quarter had zero overlap with "today's" quarter, so the cap check always
    computed requested_in_period=0 and passed regardless of how many days
    were requested — the two submissions below (10 + 10 = 20 days, cap 15)
    would both have succeeded under the old code.
    """
    s = create_soldier(admin_session, personal_number=_pn(21))
    far_anchor = date.today() + timedelta(days=200)
    period_start, _period_end = constraints.period_bounds("quarter", far_anchor)

    first_start = period_start + timedelta(days=1)
    first_end = first_start + timedelta(days=9)  # 10 days
    submit_constraint(
        admin_session, soldier_id=s.id,
        start_date=first_start, end_date=first_end, reason="a", actor_id=None,
    )
    admin_session.commit()

    second_start = first_end + timedelta(days=1)
    second_end = second_start + timedelta(days=9)  # another 10 days, same quarter
    with pytest.raises(ConstraintError, match="cap_exceeded"):
        submit_constraint(
            admin_session, soldier_id=s.id,
            start_date=second_start, end_date=second_end, reason="b", actor_id=None,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_constraints_service.py::test_submit_cap_checked_against_requests_own_quarter_not_submission_day -v`
Expected: FAIL — no `ConstraintError` is raised (both submissions succeed).

- [ ] **Step 3: Fix the implementation**

In `backend/app/services/constraints.py`, `submit_constraint` (around line 44) currently reads:

```python
    rd = remaining_days(session, soldier_id=soldier_id)
```

Change it to anchor the period on the request's own start date instead of the real submission-time date:

```python
    rd = remaining_days(session, soldier_id=soldier_id, today=start_date)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_constraints_service.py -v`
Expected: PASS — all tests in the file, including `test_submit_cap_check_is_period_scoped_not_full_future_span` and `test_submit_cap_enforced` (both use `start_date` within a few days of real `date.today()`, so the anchor change doesn't affect their period).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/constraints.py backend/tests/unit/test_constraints_service.py
git commit -m "fix: anchor personal-constraint cap check on the request's own quarter, not submission day"
```

### Part B — Backend: widen cancel to `pending_duty_manager`

- [ ] **Step 6: Update the two tests whose old assertions describe the behavior being changed**

In `backend/tests/unit/test_constraints_service.py`, replace `test_cancel_not_pending` (lines 259-273) — it currently drives the constraint to `pending_duty_manager` via a single `approve_constraint` call and asserts cancel is rejected; that's exactly the case now being allowed, so rewrite it to actually test the *fully approved* (both steps done) case, which must still be rejected:

```python
def test_cancel_not_pending_once_fully_approved(admin_session):
    s = create_soldier(admin_session, personal_number="7400010")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)  # -> pending_duty_manager
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)  # -> approved
    admin_session.flush()
    with pytest.raises(ConstraintError, match="not_pending"):
        cancel_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
```

Replace `test_cancel_not_pending_after_commander_step_with_no_actor` (lines 276-302) — its whole purpose was asserting cancel is rejected once `pending_duty_manager` is reached; that assertion is now backwards, so rewrite it to confirm the *opposite*, while preserving the original regression's real point (that `commander_approved_by is None` must not change the outcome):

```python
def test_cancel_at_pending_duty_manager_succeeds_regardless_of_commander_actor_id(admin_session):
    # Regression test: _approve_commander_step sets c.commander_approved_by =
    # actor_id, which can be None (actor_id is an optional kwarg on
    # approve_constraint). cancel_constraint's eligibility must be based
    # purely on `status`, not on commander_approved_by being set — a
    # commander-step approval performed with actor_id=None must not change
    # whether the now-pending_duty_manager request can still be cancelled.
    s = create_soldier(admin_session, personal_number=_pn(12))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    assert c.status == "pending_commander"
    approved = approve_constraint(admin_session, constraint_id=c.id, actor_id=None)
    admin_session.flush()
    assert approved.status == "pending_duty_manager"
    assert approved.commander_approved_by is None
    c_id = c.id
    cancel_constraint(admin_session, constraint_id=c_id, actor_id=s.id)
    admin_session.commit()
    assert admin_session.get(PersonalConstraint, c_id) is None
```

Also add one more new test confirming the single-step case (the common path):

```python
def test_cancel_during_pending_duty_manager_succeeds(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(22))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    c_id = c.id
    cancel_constraint(admin_session, constraint_id=c_id, actor_id=s.id)
    admin_session.commit()
    assert admin_session.get(PersonalConstraint, c_id) is None
```

- [ ] **Step 7: Run tests to verify the three above fail as expected**

Run: `cd backend && pytest tests/unit/test_constraints_service.py -k "cancel" -v`
Expected: FAIL on `test_cancel_not_pending_once_fully_approved` (no error currently raised — old code lets `approved` through untouched since it's not `pending_commander` either, so this one might actually already pass; verify), FAIL on the other two (they currently expect/get a raised `ConstraintError` that step 8 will remove).

- [ ] **Step 8: Fix the implementation**

In `backend/app/services/constraints.py`, `cancel_constraint` (lines 245-278) currently reads:

```python
def cancel_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    # Only the first step (pending_commander) is cancelable. Reaching
    # pending_duty_manager always means the request has moved past the first
    # approval gate - either the commander step ran (via _approve_commander_step,
    # regardless of whether actor_id was supplied - an internal/system caller
    # passing actor_id=None must not make an already-approved request look
    # uncancelable to detect), or the commander step was configured off entirely
    # and the request started directly at pending_duty_manager. Either way the
    # request is already in front of the duty manager and should no longer be
    # withdrawable unilaterally. commander_approved_by is purely an attribution
    # field (who approved it, if anyone) - it must not gate cancel eligibility,
    # both because actor_id is optional and because the FK is ON DELETE SET NULL
    # (a later soldier deletion would silently flip it back to None).
    cancelable = c.status == "pending_commander"
    if not cancelable:
        raise ConstraintError("not_pending")
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.cancel",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": c.status},
        after={"deleted": True},
    )
    session.delete(c)
```

Replace the eligibility comment and check so both pending statuses are cancelable, but a fully `approved`/`rejected`/`cancelled` request is not:

```python
def cancel_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    # Either pending step (pending_commander or pending_duty_manager) is
    # cancelable — a soldier can retract a request at any point before it's
    # actually decided. commander_approved_by is purely an attribution field
    # (who approved the commander step, if anyone) - it must not gate cancel
    # eligibility, both because actor_id is optional on approve_constraint and
    # because the FK is ON DELETE SET NULL (a later soldier deletion would
    # silently flip it back to None). Once approved/rejected the request is
    # final and no longer withdrawable unilaterally.
    cancelable = c.status in ("pending_commander", "pending_duty_manager")
    if not cancelable:
        raise ConstraintError("not_pending")
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.cancel",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": c.status},
        after={"deleted": True},
    )
    session.delete(c)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_constraints_service.py -v`
Expected: PASS — full file, including `test_cancel_pending` (unchanged, still `pending_commander` → success).

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/constraints.py backend/tests/unit/test_constraints_service.py
git commit -m "feat: allow retracting a personal constraint through the pending_duty_manager step"
```

### Part C — Frontend: cancel button + stale comment

- [ ] **Step 11: Write the failing test**

Add to `frontend/src/pages/MyRequestsPage.test.tsx`, in a new `describe` block:

```tsx
describe("MyRequestsPage - retraction through pending_duty_manager", () => {
  it("shows the cancel button for a constraint pending duty-manager approval", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      { ...constraint, status: "pending_duty_manager" },
    ]);
    renderPage();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).getByTestId("cancel-c1")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- MyRequestsPage -t "retraction through pending_duty_manager"`
Expected: FAIL — `cancel-c1` is not in the document (button only renders for `"pending"`/`"pending_commander"`).

- [ ] **Step 3: Fix the implementation**

In `frontend/src/pages/MyRequestsPage.tsx`, the pending-constraints block (lines 226-243) reads:

```tsx
              {items.filter((c) => c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager").map((c) => (
                <li key={c.id} className="border dark:border-gray-600 rounded-lg p-3 bg-white dark:bg-gray-800 flex flex-col gap-2" data-testid={`constraint-row-${c.id}`}>
                  <div className="flex items-center gap-3">
                    <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                    <DaysBadge start={c.start_date} end={c.end_date} />
                    <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                    {statusBadge(c.status)}
                    {/* Only the first approval step (pending_commander) is cancelable —
                        see cancel_constraint in backend/app/services/constraints.py.
                        Once it reaches pending_duty_manager it can no longer be
                        withdrawn unilaterally, so hide the button to avoid a call
                        that would 400. */}
                    {(c.status === "pending" || c.status === "pending_commander") && (
                      <button className="text-red-500 text-xs" onClick={() => onCancel(c.id)} data-testid={`cancel-${c.id}`}>
                        {t("my_requests.cancel")}
                      </button>
                    )}
                  </div>
                  <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                </li>
              ))}
```

Replace the comment and condition so both pending steps show the cancel button, matching the widened backend eligibility:

```tsx
              {items.filter((c) => c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager").map((c) => (
                <li key={c.id} className="border dark:border-gray-600 rounded-lg p-3 bg-white dark:bg-gray-800 flex flex-col gap-2" data-testid={`constraint-row-${c.id}`}>
                  <div className="flex items-center gap-3">
                    <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                    <DaysBadge start={c.start_date} end={c.end_date} />
                    <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                    {statusBadge(c.status)}
                    {/* Either pending step is cancelable — see cancel_constraint
                        in backend/app/services/constraints.py. Once approved or
                        rejected it's final, so hide the button to avoid a call
                        that would 400. */}
                    {(c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager") && (
                      <button className="text-red-500 text-xs" onClick={() => onCancel(c.id)} data-testid={`cancel-${c.id}`}>
                        {t("my_requests.cancel")}
                      </button>
                    )}
                  </div>
                  <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                </li>
              ))}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- MyRequestsPage`
Expected: PASS — full file.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MyRequestsPage.tsx frontend/src/pages/MyRequestsPage.test.tsx
git commit -m "feat: show the cancel button through the pending_duty_manager step"
```

---

## Task 3: Fix double-approve — disable in-flight buttons + two-step indicator

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Test: `frontend/src/pages/ApprovalsPage.test.tsx`

**Interfaces:**
- Consumes: existing `onApprove`, `onErApproveCommander`, `onErApproveDutyManager`, `onFuApprove`, `onTransferApprove`, `onSwapManagerApprove` functions — signatures unchanged.
- Produces: a new local `pendingIds: Set<string>` state; approve buttons gain `disabled={pendingIds.has(key)}`. No other task depends on this.

- [ ] **Step 1: Write the failing test — button disables while in flight**

Add to `frontend/src/pages/ApprovalsPage.test.tsx`, in a new `describe` block. This uses a controllable promise so the test can assert the button is disabled *before* the mutation resolves:

```tsx
describe("ApprovalsPage - in-flight approve button", () => {
  it("disables the constraint approve button while the request is in flight", async () => {
    let resolveApprove: (v: constraintsApi.PersonalConstraint) => void;
    vi.mocked(constraintsApi.approveConstraint).mockReturnValue(
      new Promise((resolve) => { resolveApprove = resolve; })
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SoldierModalProvider>
            <ApprovalsPage />
          </SoldierModalProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const approveBtn = await screen.findByTestId("approve-c1");
    fireEvent.click(approveBtn);
    await waitFor(() => expect(approveBtn).toBeDisabled());
    resolveApprove!(constraint);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ApprovalsPage -t "disables the constraint approve button"`
Expected: FAIL — the button has no `disabled` attribute at all currently.

- [ ] **Step 3: Fix the implementation — add in-flight tracking**

In `frontend/src/pages/ApprovalsPage.tsx`, add a new piece of state next to the existing `actionError` state (around line 173):

```tsx
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
```

Add a small helper right after that (any of the approve/reject handlers can call it):

```tsx
  function withPending<T>(key: string, fn: () => Promise<T>): Promise<T> {
    setPendingIds((prev) => new Set(prev).add(key));
    return fn().finally(() => {
      setPendingIds((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    });
  }
```

Wrap every approve call site's body in `withPending`. `onApprove` (around line 221) changes from:

```tsx
  async function onApprove(id: string) {
    try {
      await approveConstraint(id);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingConstraints() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingConstraintsCount() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }
```

to:

```tsx
  async function onApprove(id: string) {
    try {
      await withPending(`constraint-${id}`, () => approveConstraint(id));
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingConstraints() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingConstraintsCount() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }
```

Apply the same `withPending(key, () => ...)` wrap, each with its own unique key prefix, to:
- `onErApproveCommander(id)` → key `` `er-commander-${id}` ``
- `onErApproveDutyManager(id)` → key `` `er-duty-manager-${id}` ``
- `onFuApprove(item)` → key `` `fu-${item.id}` ``
- `onTransferApprove(id)` → key `` `transfer-${id}` ``
- `onSwapManagerApprove(id, side, candidateId?)` → key `` `swap-${id}-${side}-${candidateId ?? "none"}` ``

Then wire each button's `disabled` prop to check the matching key. The constraint approve button (around line 470) changes from:

```tsx
                    <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onApprove(c.id)} data-testid={`approve-${c.id}`}>
                      {t("approvals.approve")}
                    </button>
```

to:

```tsx
                    <button
                      className="bg-green-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                      onClick={() => onApprove(c.id)}
                      disabled={pendingIds.has(`constraint-${c.id}`)}
                      data-testid={`approve-${c.id}`}
                    >
                      {t("approvals.approve")}
                    </button>
```

Apply the equivalent `disabled={pendingIds.has(<matching key>)}` + `disabled:opacity-50` class addition to the exemption commander/duty-manager approve buttons (lines 545-553), the field-update approve button (line 608), and the transfer approve button (line 810-814). For the swap manager approve button inside `SwapKindApproval` (lines 83-108), thread a new `disabled` prop through:

```tsx
function SwapKindApproval({
  approvals, label, canAct, onApprove, t, disabled,
}: {
  approvals: DirectCommanderApprovalRow[];
  label: string;
  canAct: boolean;
  onApprove: () => void;
  t: (k: string) => string;
  disabled: boolean;
}) {
  if (approvals.length === 0) return null;
  const done = isSideSatisfied(approvals);
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span>{label}:</span>
      <DirectCommanderApproval approvals={approvals} />
      {!done && canAct && (
        <button
          onClick={onApprove}
          disabled={disabled}
          className="bg-green-600 text-white px-2 py-0.5 rounded text-xs disabled:opacity-50"
        >
          {t("approvals.approve")}
        </button>
      )}
    </div>
  );
}
```

and pass `disabled={pendingIds.has(\`swap-${swap.id}-requester-none\`)}` / the matching covering-side key at each `<SwapKindApproval .../>` call site.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- ApprovalsPage`
Expected: PASS — full file, including all pre-existing tests (none of them assert `disabled` is absent, so this is additive).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/ApprovalsPage.test.tsx
git commit -m "fix: disable approve buttons while their request is in flight"
```

- [ ] **Step 6: Write the failing test — two-step indicator for constraints**

Add to `frontend/src/pages/ApprovalsPage.test.tsx`:

```tsx
describe("ApprovalsPage - two-step indicator", () => {
  it("shows a step indicator on a constraint still pending the commander step", async () => {
    vi.mocked(constraintsApi.listPendingApprovals).mockResolvedValue([
      { ...constraint, status: "pending_commander" },
    ]);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SoldierModalProvider>
            <ApprovalsPage />
          </SoldierModalProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const row = await screen.findByTestId("approval-row-c1");
    expect(within(row).getByTestId("constraint-stage-c1")).toHaveTextContent("1/2");
  });

  it("shows step 2/2 on a constraint pending the duty-manager step", async () => {
    vi.mocked(constraintsApi.listPendingApprovals).mockResolvedValue([
      { ...constraint, status: "pending_duty_manager" },
    ]);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SoldierModalProvider>
            <ApprovalsPage />
          </SoldierModalProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const row = await screen.findByTestId("approval-row-c1");
    expect(within(row).getByTestId("constraint-stage-c1")).toHaveTextContent("2/2");
  });
});
```

Note: both tests need `import { within } from "@testing-library/react"` — check the top of the file; if `within` isn't already imported from `"@testing-library/react"`, add it to the existing import on line 1.

- [ ] **Step 7: Run test to verify it fails**

Run: `cd frontend && npm test -- ApprovalsPage -t "two-step indicator"`
Expected: FAIL — `constraint-stage-c1` does not exist.

- [ ] **Step 8: Fix the implementation**

In `frontend/src/pages/ApprovalsPage.tsx`, in the constraints tab's row (around line 456-459, right after the soldier-name line and before the date line), add a stage paragraph mirroring the existing exemption-request `er-stage` pattern (lines 514-520):

```tsx
                  <div className="flex items-center gap-2 mb-1">
                    <strong className="text-sm"><SoldierLink id={c.soldier_id} name={c.soldier_name || c.soldier_id.slice(0, 8)} /></strong>
                    {c.node_name && <span className="text-xs text-gray-400">{c.node_name}</span>}
                  </div>
                  {(c.status === "pending_commander" || c.status === "pending_duty_manager") && (
                    <p className="text-xs text-gray-500 mb-1" data-testid={`constraint-stage-${c.id}`}>
                      {c.status === "pending_commander" ? "שלב 1/2 — ממתין לאישור מפקד" : "שלב 2/2 — ממתין לאישור אג\"ם"}
                    </p>
                  )}
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd frontend && npm test -- ApprovalsPage`
Expected: PASS — full file.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/ApprovalsPage.test.tsx
git commit -m "feat: show a 1/2 or 2/2 step indicator on two-step constraint approvals"
```

---

## Task 4: Partial Excel import — exclude whole sections

**Files:**
- Modify: `backend/app/services/import_sessions.py:1326-1327` (`_effective_action`)
- Modify: `frontend/src/api/importSessions.ts:14-18` (`Selections` type)
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx` (checklist UI + tab bar)
- Test: `backend/tests/integration/test_import_sessions_api.py`
- Test: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: existing `set_selections(session, *, session_id, selections: dict)` service function and `PATCH /import/sessions/{id}/selections` route — both already accept an arbitrary dict, no signature change needed.
- Produces: `selections["_excluded_groups"]: list[str]` — a new reserved key inside the existing generic `user_selections` dict, alongside the already-existing `_name_mappings` and `_field_overrides` keys. Every group's row-processing loop in `confirm_session` (~20 loops) picks this up automatically through `_effective_action`, with no changes to those loops.

### Part A — Backend: exclusion respected by `_effective_action`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_import_sessions_api.py`, using this file's own helpers (`_token`, `_upload`, `_to_bytes`, `_uid`, already defined near the top of the file):

```python
def test_confirm_skips_an_excluded_group_even_when_rows_would_otherwise_import(client, admin_session):
    """A group listed in selections["_excluded_groups"] must be skipped
    entirely on confirm, regardless of each row's own action."""
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("personal_constraints")
    ws.append([
        "soldier_personal_number", "start_date", "end_date", "reason",
        "status", "decided_by_personal_number", "decision_note",
    ])
    ws.append([soldier.personal_number, "2026-09-01", "2026-09-05", "חופשה", "approved", "", ""])
    xlsx = _to_bytes(wb)

    upload = _upload(client, _token(admin), xlsx)
    assert upload.status_code == 200, upload.text
    session_id = upload.json()["session_id"]

    patched = client.patch(
        f"/api/import/sessions/{session_id}/selections",
        headers={"Authorization": f"Bearer {_token(admin)}"},
        json={"selections": {"_excluded_groups": ["personal_constraints"]}},
    )
    assert patched.status_code == 200, patched.text

    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["created"] == 0
    assert confirmed.json()["skipped"] >= 1

    from app.services.constraints import list_constraints
    assert list_constraints(admin_session, soldier_id=soldier.id) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_import_sessions_api.py::test_confirm_skips_an_excluded_group_even_when_rows_would_otherwise_import -v`
Expected: FAIL — `created` is `1`, not `0`; the constraint is created.

- [ ] **Step 3: Fix the implementation**

In `backend/app/services/import_sessions.py`, `_effective_action` (lines 1326-1327) currently reads:

```python
def _effective_action(selections: dict, group: str, row: dict) -> str:
    return selections.get(group, {}).get(str(row["row"]), row["action"])
```

Change it to check the exclusion list first:

```python
def _effective_action(selections: dict, group: str, row: dict) -> str:
    if group in (selections.get("_excluded_groups") or []):
        return "skip"
    return selections.get(group, {}).get(str(row["row"]), row["action"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_import_sessions_api.py -v`
Expected: PASS — full file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/tests/integration/test_import_sessions_api.py
git commit -m "feat: skip an entire import section when listed in selections._excluded_groups"
```

### Part B — Frontend: section checklist UI

- [ ] **Step 6: Write the failing test**

This file already has a `makeDraftDetail(overrides: Partial<SessionDetail> = {})` helper (builds a full `SessionDetail` with every group defaulting to `[]`, e.g. `personal_constraints: []`) and a no-arg `renderPage()` helper, used by every existing test in this file — reuse both exactly as-is. Add a new test:

```tsx
describe("ImportSessionReviewPage - section exclusion", () => {
  it("excludes a section from confirm when its checkbox is unchecked", async () => {
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(
      makeDraftDetail({
        parsed_state: {
          ...makeDraftDetail().parsed_state,
          personal_constraints: [
            {
              row: 2,
              action: "new",
              errors: [],
              id: null,
              soldier_personal_number: "1234567",
              resolved_soldier_id: "sol-1",
              start_date: "2026-09-01",
              end_date: "2026-09-05",
              reason: "חופשה",
              status: "approved",
              decided_by_personal_number: null,
              resolved_decided_by_id: null,
              decision_note: null,
              existing_id: null,
            },
          ],
        },
      }),
    );
    renderPage();
    const checkbox = await screen.findByTestId("section-toggle-personal_constraints");
    expect(checkbox).toBeChecked();
    fireEvent.click(checkbox);
    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({ _excluded_groups: ["personal_constraints"] }),
      );
    });
  });
});
```

This matches the `PersonalConstraintImportRow` interface in `frontend/src/api/importSessions.ts:251-263` exactly (`RowBase` fields `row`/`action`/`errors` plus `id`, `soldier_personal_number`, `resolved_soldier_id`, `start_date`, `end_date`, `reason`, `status`, `decided_by_personal_number`, `resolved_decided_by_id`, `decision_note`, `existing_id`).

- [ ] **Step 7: Run test to verify it fails**

Run: `cd frontend && npm test -- ImportSessionReviewPage -t "excludes a section from confirm"`
Expected: FAIL — `section-toggle-personal_constraints` does not exist.

- [ ] **Step 8: Fix the implementation**

In `frontend/src/api/importSessions.ts`, widen the `Selections` type (lines 14-18) to allow the new key:

```ts
export interface Selections {
  _name_mappings?: NameMappings;
  _field_overrides?: Record<string, Record<string, Record<string, unknown>>>;
  _excluded_groups?: string[];
  [group: string]: Record<string, string> | NameMappings | Record<string, Record<string, Record<string, unknown>>> | string[] | undefined;
}
```

In `frontend/src/pages/ImportSessionReviewPage.tsx`, add a helper right after `setRowAction` (after line 364) that toggles a whole group's membership in `_excluded_groups` and persists it the same way `setRowAction` does:

```tsx
  function toggleGroupExcluded(group: GroupKey, excluded: boolean) {
    if (!id) return;
    setSelections((prev) => {
      const current = new Set(prev._excluded_groups ?? []);
      if (excluded) current.add(group); else current.delete(group);
      const next: Selections = { ...prev, _excluded_groups: Array.from(current) };
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        void saveSelections(id, next);
      }, 500);
      return next;
    });
  }
```

Replace the tab-bar block (lines 545-583) so the `[key, label]` list is built once, reused for both the new checklist and the existing tab buttons, and each entry with at least one row gets a checkbox:

```tsx
        <div className="space-y-2">
          {(() => {
            const sections: [TabKey, string, number][] = [
              ["soldiers", "חיילים", soldiers.length],
              ["duty_shifts", "משמרות", duty_shifts.length],
              ["shift_templates", "תבניות", shift_templates.length],
              ["assignments", "שיבוצים", assignments.length],
              ["duty_locations", "מיקומי תורנות", duty_locations.length],
              ["hierarchy", "היררכיה", hierarchy.length],
              ["duty_types", "סוגי תורנות", duty_types.length],
              ["exemption_types", "פטורים", exemption_types.length],
              ["system_settings", "הגדרות מערכת", system_settings.length],
              ["bug_reports", "דוחות תקלות", bug_reports.length],
              ["personal_constraints", "אילוצים אישיים", personal_constraints.length],
              ["soldier_field_updates", "עדכוני שדות", soldier_field_updates.length],
              ["soldier_enrollment_requests", "בקשות שיבוץ", soldier_enrollment_requests.length],
              ["soldier_exemptions", "פטורי חיילים", soldier_exemptions.length],
              ["exemption_requests", "בקשות פטור", exemption_requests.length],
              ["swap_requests", "בקשות החלפה", swap_requests.length],
              ["range_locations", "מיקומי מטווח", range_locations.length],
              ["range_events", "מטווחים", range_events.length],
              ["range_assignments", "שיבוצי מטווח", range_assignments.length],
              ["soldier_range_qualifications", "כשירויות מטווח", soldier_range_qualifications.length],
              ["range_excusal_requests", "בקשות פטור ממטווח", range_excusal_requests.length],
            ];
            const excludedGroups = new Set(selections._excluded_groups ?? []);
            const detected = sections.filter(([, , count]) => count > 0);
            return (
              <>
                {detected.length > 0 && (
                  <div className="flex flex-wrap gap-3 bg-gray-50 dark:bg-gray-900 rounded p-2 text-sm">
                    {detected.map(([key, label]) => {
                      const excluded = excludedGroups.has(key);
                      return (
                        <label key={key} className="flex items-center gap-1 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={!excluded}
                            disabled={readOnly}
                            onChange={(e) => toggleGroupExcluded(key, !e.target.checked)}
                            data-testid={`section-toggle-${key}`}
                          />
                          <span className={excluded ? "text-gray-400 line-through" : ""}>{label}</span>
                        </label>
                      );
                    })}
                  </div>
                )}
                <div className="flex gap-2 border-b dark:border-gray-700 flex-wrap">
                  {sections.map(([key, label, count]) => {
                    const excluded = excludedGroups.has(key);
                    return (
                      <button
                        key={key}
                        className={`px-3 py-2 text-sm font-medium ${
                          tab === key
                            ? "border-b-2 border-indigo-600 text-indigo-600"
                            : excluded
                            ? "text-gray-300"
                            : "text-gray-500"
                        }`}
                        onClick={() => setTab(key)}
                      >
                        {label} ({count}){excluded ? " — לא ייובא" : ""}
                      </button>
                    );
                  })}
                </div>
              </>
            );
          })()}
        </div>
```

This replaces the previous single `<div className="flex gap-2 ...">...</div>` tab bar block entirely — delete the old block shown in the read-only excerpt above (the one built from the inline `[TabKey, string][]` array with the `.map(([key, label]) => ...)` button list) and put this new block in its place, in the same position in the JSX (right after the `{error && (...)}` block, before `{tab === "soldiers" && (...)}`).

- [ ] **Step 9: Run test to verify it passes**

Run: `cd frontend && npm test -- ImportSessionReviewPage`
Expected: PASS — full file, including all pre-existing tab-bar-related tests (button text now includes the count in parens like before, so existing assertions on button text like `"חיילים (2)"` should be unaffected — double check any exact-text assertions against tab labels still match, since the label format `"{label} ({count})"` matches the old inline format `` `{label} (${count})` `` exactly).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/importSessions.ts frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: add a per-section include/exclude checklist to the import review page"
```

---

## Task 5: Surface "waiting on X" to the requester in MyRequestsPage

**Files:**
- Modify: `frontend/src/pages/MyRequestsPage.tsx`
- Test: `frontend/src/pages/MyRequestsPage.test.tsx`

**Interfaces:**
- Consumes: `PersonalConstraint.nearest_commander`/`nearest_duty_manager` (already on the type, `frontend/src/api/constraints.ts:16-17`) and `ExemptionRequest.nearest_commander`/`nearest_duty_manager` (already on the type, `frontend/src/api/exemptions.ts:62-63`) — both already returned by the backend for `/me/constraints` and the soldier's own exemption-request list respectively (verify the exemption-request one during Step 3 below; the constraints one is already confirmed).
- Produces: no new exports; purely additive JSX in this one page.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/MyRequestsPage.test.tsx`:

```tsx
describe("MyRequestsPage - waiting-on visibility", () => {
  it("shows who a pending_commander constraint is waiting on", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      {
        ...constraint,
        status: "pending_commander",
        nearest_commander: { id: "cmd-1", name: "רס\"ן לוי" },
        nearest_duty_manager: { id: "dm-1", name: "סמ\"ר כהן" },
      },
    ]);
    renderPage();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).getByTestId("constraint-waiting-on-c1")).toHaveTextContent("רס\"ן לוי");
  });

  it("shows the duty manager once the commander step is done", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      {
        ...constraint,
        status: "pending_duty_manager",
        nearest_commander: { id: "cmd-1", name: "רס\"ן לוי" },
        nearest_duty_manager: { id: "dm-1", name: "סמ\"ר כהן" },
      },
    ]);
    renderPage();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).getByTestId("constraint-waiting-on-c1")).toHaveTextContent("סמ\"ר כהן");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- MyRequestsPage -t "waiting-on visibility"`
Expected: FAIL — `constraint-waiting-on-c1` does not exist.

- [ ] **Step 3: Check whether exemption requests already expose the same fields end-to-end**

Read `backend/app/routes/exemption_requests.py` around the route that serves the soldier's own list (`GET /me/exemption-requests` or equivalent — the one that calls `_nearest_approvers` and passes `nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager` into `_out(...)`, confirmed present around line 231-234 during planning) to confirm it's the *list* endpoint (not just the *submit* response). If confirmed, no backend change needed for exemption requests — skip straight to Step 4 and add the same badge to the exemption-request list too. If the list endpoint does NOT already pass nearest approvers (only the single-object submit/approve responses do), add the same `nearest_commander, nearest_duty_manager = _nearest_approvers(session, user.id)` call and pass-through to that list route's `_out(...)` calls, following the exact pattern already used at the other call sites in that file (e.g. line 231-234).

- [ ] **Step 4: Fix the implementation**

In `frontend/src/pages/MyRequestsPage.tsx`, add a small helper above the component (after the imports, before `export default function MyRequestsPage()`):

```tsx
function waitingOnLabel(
  status: string,
  nearestCommander: { id: string; name: string } | null,
  nearestDutyManager: { id: string; name: string } | null,
): string | null {
  if (status === "pending_commander" || status === "pending") {
    return nearestCommander?.name ?? null;
  }
  if (status === "pending_duty_manager") {
    return nearestDutyManager?.name ?? null;
  }
  return null;
}
```

In the pending-constraints block (lines 226-243), add the badge right after the `statusBadge(c.status)}` line:

```tsx
                    {statusBadge(c.status)}
                    {(() => {
                      const waitingOn = waitingOnLabel(c.status, c.nearest_commander, c.nearest_duty_manager);
                      return waitingOn ? (
                        <span className="text-xs text-gray-500 dark:text-gray-400" data-testid={`constraint-waiting-on-${c.id}`}>
                          ממתין ל: {waitingOn}
                        </span>
                      ) : null;
                    })()}
```

Add the equivalent badge to the exemption-request list (lines 449-467), inside the existing `<li>` right after the status `<span>` (around line 461):

```tsx
                  <span className={`text-xs ${
                    er.status === "approved" ? "text-green-600 dark:text-green-400" :
                    er.status === "rejected" ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"
                  }`}>{t(`exemption_requests.${er.status}`)}</span>
                  {(() => {
                    const waitingOn = waitingOnLabel(er.status, er.nearest_commander, er.nearest_duty_manager);
                    return waitingOn ? (
                      <span className="text-xs text-gray-500 dark:text-gray-400" data-testid={`er-waiting-on-${er.id}`}>
                        ממתין ל: {waitingOn}
                      </span>
                    ) : null;
                  })()}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test -- MyRequestsPage`
Expected: PASS — full file.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/MyRequestsPage.tsx frontend/src/pages/MyRequestsPage.test.tsx
git commit -m "feat: show who a pending request is waiting on in MyRequestsPage"
```

(If Step 3 required a backend change, also run `cd backend && pytest app/services/tests/test_import_approvals_service.py tests/integration/test_constraints_api.py -v` — or whichever backend test file covers the touched route — before this commit, and include the modified backend route file + its test in this same commit.)

---

## Final Integration Check

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && pytest -q`
Expected: PASS, no failures. (Skip `--slow`.)

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd frontend && npm test`
Expected: PASS, no failures.

- [ ] **Step 3: Run frontend lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: PASS, zero warnings.

- [ ] **Step 4: Manual smoke check in the browser** (see project skill `run` / the dev-stack instructions in `CLAUDE.md`)

Start the dev stack (`.\dev.ps1` from the repo root), then:
- As a soldier: submit a personal constraint, confirm the "waiting on" badge shows the commander's name, confirm the cancel button is present while `pending_duty_manager`.
- As a commander/duty manager: open Approvals, click approve on a constraint, confirm the button disables immediately and the step indicator shows `1/2` before the click and disappears (or shows `2/2`) after.
- As an admin: start an Excel import with a workbook containing at least two sections (e.g. `duty_types` and `personal_constraints`), uncheck one section's checkbox, confirm the session, and verify only the checked section's rows were created.
