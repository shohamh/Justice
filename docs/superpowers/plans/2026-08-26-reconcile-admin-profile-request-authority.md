# Reconcile admin-profile-request-authority duplicate work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the small set of user-visible gaps between `dev`'s already-merged "admin profiles and request authority" feature and the independently-built `feature/admin-profile-request-authority` worktree onto `dev`, without reintroducing the worktree's incompatible schema/endpoint/authority-naming choices.

**Background:** Two independent implementations of the same spec were built in parallel. `dev` already merged its own version (commits `422f45cd..2fa6dc84`) before the `feature/admin-profile-request-authority` worktree (built from the superseded plan at `docs/superpowers/plans/2026-08-26-admin-profiles-and-request-cancellation.md`) finished. A comparison found the two are **not mechanically mergeable**: different REST verbs/paths for cancellation (`POST /constraints/{id}/cancel` vs `DELETE /constraints/{id}`), different persistence models (`dev` reuses existing `decided_by`/`decided_at`/`decision_note` columns; the worktree added new `cancelled_at`/`cancelled_by`/`cancel_reason` columns and a migration), different error codes (`cancellation_reason_required` vs `reason_required`), different notification enum values, and different authority-predicate names. `dev`'s version is treated as the integration base because it is already merged, already tested, and additionally ships two things the worktree never built (server-side admin-promotion-confirmation enforcement, and extra profile fields). This plan ports forward only the worktree's genuine value-adds — cancellation-reason visibility in history/self-service views, i18n coverage, and warning-styled cancellation modals — re-implemented against `dev`'s actual schema and function names, plus the worktree's stronger test coverage adapted to match.

**Architecture:** Backend: extend the existing `personal_constraint` duty-history timeline event (already gated by `include_sensitive`, mirroring the existing `SoldierExemption` revocation pattern in the same function) with a resolved canceller name. Frontend: add a dedicated attribution line to `DutyHistoryPanel` mirroring its existing exemption-revocation block, add a "cancelled" bucket to `MyRequestsPage`'s personal-constraints section (the real functional gap — a cancelled constraint currently renders in none of the page's status groups), and add an optional warning-styled variant to the already-shared `ReasonPromptModal` component used by both exemption revocation and constraint cancellation.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React, TypeScript, Vitest, React Query, i18next.

**Spec:** `docs/superpowers/specs/2026-08-26-admin-profiles-and-request-cancellation-design.md` (the original spec both implementations argue from; `dev`'s design choices are treated as satisfying it and are not revisited by this plan except where explicitly noted below).

## Global Constraints

- Do not change `dev`'s cancellation endpoint (`POST /constraints/{id}/cancel`), persistence model (`decided_by`/`decided_at`/`decision_note` reused columns), error code (`cancellation_reason_required`), notification type (`constraint_rejected`), or authority-predicate names (`request_cancellation_authorized`, `senior_commander_approval_authorized`). These are `dev`'s existing, already-shipped choices — this plan is additive only.
- Do not port the worktree's `commander_approval_authorized` (which excludes duty managers from the commander-approval step). `dev`'s `_can_approve_constraint`/`approve()` deliberately preserve pre-existing duty-manager eligibility on that step via a fallback to `Action.CONSTRAINT_APPROVE`; the spec's line "Existing duty-manager approval rules are unchanged" is satisfied by leaving this alone. This is a ruling, not an oversight — do not "fix" it.
- Do not add a migration or new DB columns. Every field this plan needs (`decision_note`, `decided_by`, `decided_at`, `status`) already exists on `PersonalConstraint`.
- Work directly on `dev` in a new branch off `dev` (per this repo's branch workflow) — do not touch the now-superseded `.worktrees/admin-profile-request-authority` worktree except to remove it in Task 4.
- Hebrew UI strings added by this plan must go through `frontend/src/i18n/he.json`, not hardcoded literals — this also applies to the two existing hardcoded warning strings this plan touches (see Task 3).

## Files and responsibilities

- `backend/app/services/duty_history.py`: personal-constraint timeline event, cancellation attribution metadata.
- `backend/app/services/tests/test_duty_history.py`: attribution metadata tests.
- `frontend/src/components/DutyHistoryPanel.tsx`, `DutyHistoryPanel.test.tsx`: cancellation attribution display.
- `frontend/src/pages/MyRequestsPage.tsx`, `MyRequestsPage.test.tsx`: cancelled-constraints visibility section.
- `frontend/src/components/ReasonPromptModal.tsx`, new `ReasonPromptModal.test.tsx`: warning variant.
- `frontend/src/components/ExemptionsPanel.tsx`, `ExemptionsPanel.test.tsx`: wire warning variant into the revoke modal.
- `frontend/src/components/UnifiedSoldierModal.tsx`, `UnifiedSoldierModal.test.tsx`: wire warning variant into the constraint-cancel modal.
- `frontend/src/i18n/he.json`, `frontend/src/i18n/he.test.ts`: new/converted translation keys.

---

### Task 1: Attribute cancelled constraints in duty history

**Files:**
- Modify: `backend/app/services/duty_history.py`
- Modify: `frontend/src/components/DutyHistoryPanel.tsx`
- Test: `backend/app/services/tests/test_duty_history.py`, `frontend/src/components/DutyHistoryPanel.test.tsx`

**Interfaces:**
- Consumes: `PersonalConstraint.status`, `.decided_by`, `.decided_at`, `.decision_note` (all pre-existing columns).
- Produces: `TimelineEvent.metadata["cancelled_at"]` (ISO string) and `metadata["cancelled_by_name"]` (str), present only when `status == "cancelled"` and `include_sensitive` is true — consumed by `DutyHistoryPanel.tsx` in this same task.

- [ ] **Step 1: Write the failing backend tests**

Add to `backend/app/services/tests/test_duty_history.py`, placed near the existing `test_duty_history_annotates_revoked_exemption` / `test_duty_history_no_revocation_metadata_when_not_revoked` / `test_duty_history_hides_revocation_metadata_when_include_sensitive_false` tests (they are the direct pattern this mirrors):

```python
def test_duty_history_annotates_cancelled_constraint(admin_session):
    """A cancelled PersonalConstraint's event metadata includes cancellation details."""
    from datetime import datetime, timezone

    s = create_soldier(admin_session, personal_number=f"99{_uid()}")
    canceller = create_soldier(admin_session, personal_number=f"99{_uid()}")
    canceller.full_name = "מבטל בדיקה"
    admin_session.add(PersonalConstraint(
        soldier_id=s.id, start_date=date(2026, 6, 20), end_date=date(2026, 6, 21),
        reason="אירוע משפחתי", status="cancelled",
        decided_by=canceller.id, decided_at=datetime.now(timezone.utc),
        decision_note="כבר לא נדרש",
    ))
    admin_session.commit()

    events = get_duty_history(admin_session, s.id)
    constraint_events = [e for e in events if e.event_type == "personal_constraint"]
    assert len(constraint_events) == 1
    meta = constraint_events[0].metadata
    assert meta["cancelled_by_name"] == "מבטל בדיקה"
    assert meta["cancelled_at"] is not None
    assert meta["decision_note"] == "כבר לא נדרש"


def test_duty_history_no_cancellation_metadata_when_not_cancelled(admin_session, soldier):
    """A pending/approved PersonalConstraint's event metadata has no cancellation keys."""
    admin_session.add(PersonalConstraint(
        soldier_id=soldier.id, start_date=date(2026, 6, 20), end_date=date(2026, 6, 21),
        reason="אירוע משפחתי", status="approved",
    ))
    admin_session.commit()

    events = get_duty_history(admin_session, soldier.id)
    constraint_events = [e for e in events if e.event_type == "personal_constraint"]
    assert len(constraint_events) == 1
    assert "cancelled_by_name" not in constraint_events[0].metadata
    assert "cancelled_at" not in constraint_events[0].metadata


def test_duty_history_hides_cancellation_metadata_when_include_sensitive_false(admin_session):
    """Out-of-scope viewers (include_sensitive=False) must not see cancellation
    attribution — mirroring exemptions.py's can_see_private gate."""
    from datetime import datetime, timezone

    s = create_soldier(admin_session, personal_number=f"99{_uid()}")
    canceller = create_soldier(admin_session, personal_number=f"99{_uid()}")
    canceller.full_name = "מבטל בדיקה"
    admin_session.add(PersonalConstraint(
        soldier_id=s.id, start_date=date(2026, 6, 20), end_date=date(2026, 6, 21),
        reason="אירוע משפחתי", status="cancelled",
        decided_by=canceller.id, decided_at=datetime.now(timezone.utc),
        decision_note="כבר לא נדרש",
    ))
    admin_session.commit()

    events = get_duty_history(admin_session, s.id, include_sensitive=False)
    constraint_events = [e for e in events if e.event_type == "personal_constraint"]
    assert len(constraint_events) == 1
    meta = constraint_events[0].metadata
    assert "cancelled_by_name" not in meta
    assert "cancelled_at" not in meta
    assert "decision_note" not in meta or meta["decision_note"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend`, with `.venv` activated):
```
python -m pytest -q app/services/tests/test_duty_history.py -k cancelled_constraint or cancellation_metadata
```
Expected: FAIL — `KeyError`/`AssertionError` on `cancelled_by_name`/`cancelled_at`, since `duty_history.py` does not yet set them.

- [ ] **Step 3: Implement**

In `backend/app/services/duty_history.py`, the `PersonalConstraint` event loop currently reads (around the `# --- PersonalConstraint events ---` comment):

```python
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

Replace it with:

```python
    for c in constraints:
        constraint_metadata: dict[str, object] = {
            "decision_note": c.decision_note if include_sensitive else None,
        }
        if c.status == "cancelled" and include_sensitive:
            canceller = session.get(Soldier, c.decided_by) if c.decided_by else None
            constraint_metadata["cancelled_at"] = c.decided_at.isoformat() if c.decided_at else None
            constraint_metadata["cancelled_by_name"] = canceller.full_name if canceller else None
        events.append(
            TimelineEvent(
                id=c.id,
                event_type="personal_constraint",
                date=c.start_date.isoformat(),
                end_date=_isodate(c.end_date),
                title="אילוצים אישיים",
                description=c.reason if include_sensitive else None,
                status=c.status,
                metadata=constraint_metadata,
                created_at=c.created_at.isoformat(),
            )
        )
```

(`Soldier` is already imported in this file — it's used identically two blocks above for `se.revoked_by`.)

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest -q app/services/tests/test_duty_history.py
```
Expected: all pass, including the three new tests and the pre-existing suite (no regressions).

- [ ] **Step 5: Write the failing frontend test**

Add to `frontend/src/components/DutyHistoryPanel.test.tsx`:

```tsx
it("shows who cancelled a personal constraint when the card is expanded", async () => {
  vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue([
    {
      id: "pc1", event_type: "personal_constraint", date: "2026-06-20", end_date: "2026-06-21",
      title: "אילוצים אישיים", description: "אירוע משפחתי", status: "cancelled",
      metadata: { decision_note: "כבר לא נדרש", cancelled_by_name: "מבטל בדיקה", cancelled_at: "2026-06-19T00:00:00Z" },
      created_at: "2026-06-01T00:00:00Z",
    },
  ]);
  render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
  const card = await screen.findByTestId("history-event-personal_constraint");
  fireEvent.click(card);
  expect(within(card).getByText(/מבטל בדיקה/)).toBeTruthy();
});
```

- [ ] **Step 6: Run test to verify it fails**

```
npm test -- src/components/DutyHistoryPanel.test.tsx
```
Expected: FAIL — no element containing "מבטל בדיקה" is rendered yet.

- [ ] **Step 7: Implement**

In `frontend/src/components/DutyHistoryPanel.tsx`, immediately after the existing exemption-revocation block:

```tsx
            {e.event_type === "exemption" && e.metadata.revoke_reason && (
              <div className="text-xs text-red-600 dark:text-red-400 border-t border-gray-200 dark:border-gray-600 pt-1 mt-1">
                <span className="font-medium">בוטל</span>
                {e.metadata.revoked_by_name && <> ע״י {e.metadata.revoked_by_name}</>}
                : {e.metadata.revoke_reason}
              </div>
            )}
```

add:

```tsx
            {e.event_type === "personal_constraint" && e.status === "cancelled" && e.metadata.cancelled_by_name && (
              <p className="text-xs text-red-600 dark:text-red-400 border-t border-gray-200 dark:border-gray-600 pt-1 mt-1">
                <span className="font-medium">בוטל</span> ע״י {e.metadata.cancelled_by_name}
              </p>
            )}
```

Do not touch the existing generic `{e.metadata.decision_note && ...}` block further down — it already renders the cancellation reason text for this event (since `cancel_constraint` writes the reason into `decision_note`); this new block only adds the "cancelled by" attribution the generic block lacks.

- [ ] **Step 8: Run test to verify it passes**

```
npm test -- src/components/DutyHistoryPanel.test.tsx
```
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/duty_history.py backend/app/services/tests/test_duty_history.py frontend/src/components/DutyHistoryPanel.tsx frontend/src/components/DutyHistoryPanel.test.tsx
git commit -m "feat: attribute cancelled personal constraints in duty history"
```

---

### Task 2: Surface cancelled constraints on the soldier's own requests page

**Files:**
- Modify: `frontend/src/pages/MyRequestsPage.tsx`
- Modify: `frontend/src/i18n/he.json`
- Test: `frontend/src/pages/MyRequestsPage.test.tsx`, `frontend/src/i18n/he.test.ts` (existing coverage-check test; no new test needed there since it fails automatically if a used key is missing)

**Interfaces:**
- Consumes: `PersonalConstraint.status === "cancelled"`, `.decision_note`, `.decided_by` (`SoldierRef | null`, already typed in `frontend/src/api/constraints.ts`) — all pre-existing.
- Produces: a rendered "cancelled constraints" section, `data-testid="cancelled-constraints-list"` — nothing downstream depends on this.

**Note:** `MyRequestsPage.tsx`'s `visibleConstraints` sections currently filter by exact `c.status === "..."` equality for `"approved"`/`"rejected"` (not `statusBucket()`), so a `"cancelled"` constraint renders in none of them today — this is the real, user-facing gap this task fixes.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/MyRequestsPage.test.tsx` (find the existing test file's mock-data setup for constraints and extend it, following whatever pattern the file already uses for constraint fixtures — e.g. its existing `listMyConstraints` mock array — with one additional cancelled constraint):

```tsx
it("shows a cancelled personal constraint with its cancellation reason", async () => {
  vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
    {
      id: "c-cancelled", soldier_id: "s1", soldier_name: "x", node_name: null,
      start_date: "2026-06-20", end_date: "2026-06-21", reason: "אירוע משפחתי",
      status: "cancelled", commander_approved_by: null, waiting_on: null,
      decided_by: { id: "d1", name: "מבטל בדיקה" }, requested_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-19T00:00:00Z", decided_at: "2026-06-19T00:00:00Z",
      decision_note: "כבר לא נדרש", created_at: "2026-06-01T00:00:00Z",
      nearest_commander: null, nearest_duty_manager: null, can_approve: false, can_cancel: false,
    },
  ]);
  render(<MyRequestsPage />);
  const list = await screen.findByTestId("cancelled-constraints-list");
  expect(within(list).getByText("כבר לא נדרש")).toBeTruthy();
});
```

(Adjust the mocked module path/fixture shape to match however this test file already imports and mocks `frontend/src/api/constraints.ts` — follow its existing convention rather than introducing a new one.)

- [ ] **Step 2: Run test to verify it fails**

```
npm test -- src/pages/MyRequestsPage.test.tsx -t "cancelled personal constraint"
```
Expected: FAIL — `cancelled-constraints-list` test id does not exist.

- [ ] **Step 3: Implement — add the section**

In `frontend/src/pages/MyRequestsPage.tsx`, the personal-constraints `<section>` currently ends right after its "rejected" block:

```tsx
                        {c.decision_note && (
                          <p className="text-xs text-red-700 dark:text-red-400 mt-1">{t("my_requests.decision_note")}: {c.decision_note}</p>
                        )}
                        <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
```

Insert a new block between the closing `)}` of the rejected block and the section's closing `</section>`:

```tsx
              {visibleConstraints.filter((c) => c.status === "cancelled").length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-1.5">{t("my_requests.cancelled_constraints")}</h4>
                  <ul className="space-y-2 text-sm" data-testid="cancelled-constraints-list">
                    {visibleConstraints.filter((c) => c.status === "cancelled").map((c) => (
                      <li key={c.id} className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 bg-gray-50 dark:bg-gray-900" data-testid={`constraint-row-${c.id}`}>
                        <div className="flex items-center gap-3">
                          <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                          <DaysBadge start={c.start_date} end={c.end_date} />
                          <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                          {statusBadge(c.status)}
                        </div>
                        <RequestMetaRow
                          testIdPrefix={`constraint-${c.id}`}
                          requestedAt={c.requested_at}
                          createdAt={c.created_at}
                          updatedAt={c.updated_at}
                          waitingOn={c.waiting_on}
                          decidedBy={c.decided_by}
                          status={c.status}
                          commanderApprovedBy={c.commander_approved_by}
                        />
                        {c.decision_note && (
                          <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">{t("my_requests.decision_note")}: {c.decision_note}</p>
                        )}
                        <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
```

Also add the missing color-map entry so the status badge for "cancelled" renders in a distinct color instead of falling back to no color class. In the same file's `statusBadge` function:

```tsx
  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "text-amber-600 dark:text-amber-400",
      pending_commander: "text-amber-600 dark:text-amber-400",
      pending_duty_manager: "text-amber-600 dark:text-amber-400",
      approved: "text-green-600 dark:text-green-400",
      rejected: "text-red-600 dark:text-red-400",
    };
```

add `cancelled: "text-gray-500 dark:text-gray-400",` after the `rejected` line. (`t("my_requests.cancelled")` already resolves — that key exists in `he.json` today, used elsewhere for swap status; only the color-map entry and this new section are missing.)

- [ ] **Step 4: Add the i18n key**

In `frontend/src/i18n/he.json`, under the `"my_requests"` object, immediately after `"rejected_constraints": "אילוצים שנדחו",` add:

```json
    "cancelled_constraints": "אילוצים שבוטלו",
```

- [ ] **Step 5: Run tests to verify they pass**

```
npm test -- src/pages/MyRequestsPage.test.tsx src/i18n/he.test.ts
npm run typecheck
```
Expected: all pass; typecheck clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/MyRequestsPage.tsx frontend/src/pages/MyRequestsPage.test.tsx frontend/src/i18n/he.json
git commit -m "feat: surface cancelled personal constraints on the requests page"
```

---

### Task 3: Warning-styled reason modal for extreme cancellation actions

**Files:**
- Modify: `frontend/src/components/ReasonPromptModal.tsx`
- Modify: `frontend/src/components/ExemptionsPanel.tsx`
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx`
- Modify: `frontend/src/i18n/he.json`
- Test: new `frontend/src/components/ReasonPromptModal.test.tsx`, extend `frontend/src/components/ExemptionsPanel.test.tsx`

**Interfaces:**
- Produces: `ReasonPromptModal` gains an optional `variant?: "default" | "warning"` prop (default preserves current plain-gray-text behavior) — consumed by `ExemptionsPanel.tsx` and `UnifiedSoldierModal.tsx` in this same task.

- [ ] **Step 1: Write the failing test for the new prop**

Create `frontend/src/components/ReasonPromptModal.test.tsx`:

```tsx
// frontend/src/components/ReasonPromptModal.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ReasonPromptModal from "./ReasonPromptModal";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

describe("ReasonPromptModal", () => {
  it("renders the description as plain text by default", () => {
    render(<ReasonPromptModal title="t" description="a plain reason prompt" onConfirm={vi.fn()} onClose={vi.fn()} />);
    const desc = screen.getByText("a plain reason prompt");
    expect(desc.className).not.toContain("amber");
  });

  it("renders the description with warning styling when variant is warning", () => {
    render(<ReasonPromptModal title="t" description="an extreme action" variant="warning" onConfirm={vi.fn()} onClose={vi.fn()} />);
    const desc = screen.getByText("an extreme action");
    expect(desc.className).toContain("amber");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```
npm test -- src/components/ReasonPromptModal.test.tsx
```
Expected: FAIL — TypeScript error / no `variant` prop exists yet, or the second assertion fails since no amber class is ever applied.

- [ ] **Step 3: Implement**

In `frontend/src/components/ReasonPromptModal.tsx`, change the props interface and the description rendering:

```tsx
interface Props {
  title: string;
  description?: string;
  variant?: "default" | "warning";
  confirmLabel?: string;
  onConfirm: (reason: string) => Promise<void>;
  onClose: () => void;
}

export default function ReasonPromptModal({ title, description, variant = "default", confirmLabel, onConfirm, onClose }: Props) {
```

and replace:

```tsx
        {description && <p className="text-sm text-gray-600 dark:text-gray-300 mb-3">{description}</p>}
```

with:

```tsx
        {description && variant === "warning" && (
          <p className="text-sm text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded p-2 mb-3">
            ⚠️ {description}
          </p>
        )}
        {description && variant === "default" && (
          <p className="text-sm text-gray-600 dark:text-gray-300 mb-3">{description}</p>
        )}
```

- [ ] **Step 4: Run test to verify it passes**

```
npm test -- src/components/ReasonPromptModal.test.tsx
```
Expected: both pass.

- [ ] **Step 5: Add i18n keys for the two hardcoded warning strings**

In `frontend/src/i18n/he.json`, under `"exemptions"`, immediately after the `"revoke": "בטל",` line, add:

```json
    "revoke_active_warning": "זוהי פעולה קיצונית השמורה למקרים מיוחדים. יש לנמק את הביטול.",
```

Under `"team"`, add (this namespace has no existing constraint-cancellation strings; add near the top of the object, exact position doesn't matter as long as it's inside `"team": { ... }`):

```json
    "cancel_constraint": "ביטול אילוץ אישי",
    "cancel_constraint_active_warning": "זוהי פעולה קיצונית השמורה למקרים מיוחדים. יש לנמק את הביטול.",
```

- [ ] **Step 6: Write the failing test for ExemptionsPanel wiring**

Extend the existing test in `frontend/src/components/ExemptionsPanel.test.tsx` (the one at `test("revoking an exemption requires a reason and calls revokeExemption with it", ...)`) or add a new one asserting the warning is visually distinct:

```tsx
test("the revoke confirmation shows the extreme-action warning styling", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={false} />);
  const revokeButton = await screen.findByTestId("revoke-ex1");
  fireEvent.click(revokeButton);
  const warning = await screen.findByText(/פעולה קיצונית/);
  expect(warning.className).toContain("amber");
});
```

- [ ] **Step 7: Run test to verify it fails**

```
npm test -- src/components/ExemptionsPanel.test.tsx -t "warning styling"
```
Expected: FAIL — the description currently renders plain gray, no "amber" class.

- [ ] **Step 8: Implement — wire the variant into ExemptionsPanel**

In `frontend/src/components/ExemptionsPanel.tsx`, the revoke modal currently reads:

```tsx
      {revokingId && (
        <ReasonPromptModal
          title={t("exemptions.revoke")}
          description="זוהי פעולה קיצונית השמורה למקרים מיוחדים. יש לנמק את הביטול."
          onConfirm={(reason) => onRevoke(revokingId, reason)}
          onClose={() => setRevokingId(null)}
        />
      )}
```

Change it to:

```tsx
      {revokingId && (
        <ReasonPromptModal
          title={t("exemptions.revoke")}
          description={t("exemptions.revoke_active_warning")}
          variant="warning"
          onConfirm={(reason) => onRevoke(revokingId, reason)}
          onClose={() => setRevokingId(null)}
        />
      )}
```

- [ ] **Step 9: Run tests to verify they pass**

```
npm test -- src/components/ExemptionsPanel.test.tsx
```
Expected: all pass.

- [ ] **Step 10: Implement — wire the variant into UnifiedSoldierModal**

In `frontend/src/components/UnifiedSoldierModal.tsx`, the constraint-cancel modal currently reads:

```tsx
        {cancellingConstraintId && <ReasonPromptModal title="ביטול אילוץ אישי" description="זוהי פעולה קיצונית השמורה למקרים מיוחדים. יש לנמק את הביטול." onConfirm={handleCancelConstraint} onClose={() => setCancellingConstraintId(null)} />}
```

Change it to:

```tsx
        {cancellingConstraintId && <ReasonPromptModal title={t("team.cancel_constraint")} description={t("team.cancel_constraint_active_warning")} variant="warning" onConfirm={handleCancelConstraint} onClose={() => setCancellingConstraintId(null)} />}
```

(`t` is already in scope in this component — it's used throughout for other labels.)

- [ ] **Step 11: Write the failing test for UnifiedSoldierModal wiring**

In `frontend/src/components/UnifiedSoldierModal.test.tsx`, find the existing constraint-cancellation test coverage (search for `cancel-constraint-` or `cancellingConstraintId`) and add an assertion, following that test's existing render/setup pattern:

```tsx
it("shows the extreme-action warning when cancelling an approved constraint", async () => {
  // reuse this file's existing setup that renders UnifiedSoldierModal with an
  // approved, can_cancel personal constraint, then:
  const cancelButton = await screen.findByTestId(/cancel-constraint-/);
  fireEvent.click(cancelButton);
  const warning = await screen.findByText(/פעולה קיצונית/);
  expect(warning.className).toContain("amber");
});
```

- [ ] **Step 12: Run test to verify it fails, then passes after Step 10's change**

```
npm test -- src/components/UnifiedSoldierModal.test.tsx
```
Run once before Step 10 (FAIL) is not needed since Step 10 already happened in this same task — instead just confirm it passes now:
Expected: all pass, including the new test.

- [ ] **Step 13: Run the full frontend verification for touched files**

```
npm test -- src/components/ReasonPromptModal.test.tsx src/components/ExemptionsPanel.test.tsx src/components/UnifiedSoldierModal.test.tsx src/i18n/he.test.ts
npm run typecheck
npm run lint
```
Expected: all pass, typecheck and lint clean.

- [ ] **Step 14: Commit**

```bash
git add frontend/src/components/ReasonPromptModal.tsx frontend/src/components/ReasonPromptModal.test.tsx frontend/src/components/ExemptionsPanel.tsx frontend/src/components/ExemptionsPanel.test.tsx frontend/src/components/UnifiedSoldierModal.tsx frontend/src/components/UnifiedSoldierModal.test.tsx frontend/src/i18n/he.json
git commit -m "feat: style extreme-action cancellation prompts as warnings"
```

---

### Task 4: Verification and retire the superseded worktree

**Files:**
- Modify: only touched tests/contracts/i18n files required by verification.
- Remove: `.worktrees/admin-profile-request-authority` (worktree) and its branch `feature/admin-profile-request-authority`; `.superpowers/sdd/2026-08-26-admin-profiles-and-request-cancellation/` workspace; the superseded plan/spec docs.

- [ ] **Step 1: Run the full relevant backend suite**

```
python -m pytest -q app/services/tests/test_duty_history.py app/services/tests/test_authority.py app/services/tests/test_constraints.py backend/tests/integration/test_constraints_api.py backend/tests/integration/test_exemptions_api.py
```
Expected: all pass, pristine output (no new warnings).

- [ ] **Step 2: Run the full relevant frontend suite, typecheck, and lint**

```
npm test -- src/components/DutyHistoryPanel.test.tsx src/pages/MyRequestsPage.test.tsx src/components/ReasonPromptModal.test.tsx src/components/ExemptionsPanel.test.tsx src/components/UnifiedSoldierModal.test.tsx src/i18n/he.test.ts
npm run typecheck
npm run lint
```
Expected: all pass, clean.

- [ ] **Step 3: Confirm no regression to the `dev` behaviors this plan explicitly preserves**

Manually re-read (no code change expected) `backend/app/routes/constraints.py`'s `_can_approve_constraint` and `approve()` to confirm the duty-manager fallback on the commander-approval step is untouched by this branch's diff (`git diff dev -- backend/app/routes/constraints.py` should show only unrelated hunks, if any at all).

- [ ] **Step 4: Remove the superseded worktree and its plan artifacts**

```bash
git -C "C:\Users\Shoham\workspace\Justice" worktree remove ".worktrees/admin-profile-request-authority"
git -C "C:\Users\Shoham\workspace\Justice" branch -D feature/admin-profile-request-authority
```

Then, on this reconciliation branch, remove the superseded plan/spec docs and SDD workspace (they described the abandoned parallel implementation, not this one):

```bash
git rm docs/superpowers/plans/2026-08-26-admin-profiles-and-request-cancellation.md
git rm docs/superpowers/specs/2026-08-26-admin-profiles-and-request-cancellation-design.md
```

(The `.superpowers/sdd/2026-08-26-admin-profiles-and-request-cancellation/` directory was git-ignored scratch inside the now-removed worktree — nothing to clean up here for it.)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: verify reconciled admin/request cancellation history and remove superseded plan"
```
